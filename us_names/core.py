"""Seeded name generation from source-labelled aggregate data."""
from __future__ import annotations
import bisect
import json
import random
import sqlite3
import string
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import regex

VERSION = '0.2.0'
GROUPS = ('white', 'black', 'aian', 'asian_nhpi', 'multiracial', 'hispanic')
FORMATS = {
    'given': '{given}', 'surname': '{surname}', 'name': '{given} {surname}',
    'full': '{given} {middle} {surname}',
    'double_surname': '{given} {middle} {surname} {surname2}',
    'middle_initial': '{given} {middle_initial} {surname}',
    'given_initials': '{given_initial} {middle_initial} {surname}',
    'initials': '{given_initial} {middle_initial} {surname_initial}',
    'surname_first': '{surname}, {given} {middle_initial}',
}
# Curated ordered exceptions; explicitly requested only, with no invented frequency.
COMPOUND_EXCEPTIONS = {('JOSE','MARIA'):'M', ('MARIA','JOSE'):'F'}
COMPONENTS = ('given', 'middle', 'surname', 'surname2')


def char_length(text):
    return len(regex.findall(r'\X', text))


def transform(text, query):
    text = unicodedata.normalize('NFC', text)
    if query.ascii_only:
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return {'upper': str.upper, 'lower': str.lower, 'title': str.title}.get(query.casing, lambda x:x)(text)


class NoCandidates(ValueError):
    """No eligible tokens."""


class SamplingExhausted(RuntimeError):
    """Attempt limit reached; this does NOT prove the query impossible."""


@dataclass(frozen=True)
class Query:
    format: str = 'name'
    min_length: int = 1
    max_length: int | None = None
    component_lengths: dict[str, tuple[int, int | None]] = field(default_factory=dict)
    use_frequency_weights: bool = True
    given_pair: tuple[str, str] | None = None
    gender: str = 'auto'
    min_gender_share: float = 0.05
    group: str | None = 'auto'
    min_group_share: float = 0.05
    birth_year_range: tuple[int, int] | None = None
    casing: str = 'source'
    ascii_only: bool = False
    initial_period: bool = True
    max_attempts: int = 10000


from .database import Dataset


class Generator:
    """SQL-filtered candidate pools; one generator per worker, bounded instance caches."""
    def __init__(self,dataset,seed=None):
        self.dataset,self.seed=dataset,seed
        self.random=random.Random(seed)
        self.dataset_version=dataset.metadata().get('dataset_version','unversioned')
        self._pools={}
        self._records={}
        self._cohort_years=None

    def _cohort(self,years):
        if getattr(self.dataset,'_cohort_years',None)==years:return
        c=self.dataset.connection
        c.execute('DROP TABLE IF EXISTS temp.cohort_counts')
        c.execute('CREATE TEMP TABLE cohort_counts(name_id INTEGER, sex TEXT, count REAL, share REAL, PRIMARY KEY(name_id,sex)) WITHOUT ROWID')
        c.execute('INSERT INTO cohort_counts SELECT name_id,sex,SUM(count),0 FROM name_year_sex_counts WHERE year BETWEEN ? AND ? GROUP BY name_id,sex',years)
        c.execute('UPDATE cohort_counts AS s SET share=count/(SELECT SUM(t.count) FROM cohort_counts t WHERE t.name_id=s.name_id)')
        self.dataset._cohort_years=years

    def _pool(self,role,group,gender,q,bounds):
        years=tuple(q.birth_year_range) if q.birth_year_range and role=='given' else None
        gender=gender if role=='given' else None
        key=(role,group,gender,years,q.use_frequency_weights,q.min_group_share,q.min_gender_share,*bounds,q.casing,q.ascii_only)
        if key in self._pools:return self._pools[key]
        if years:self._cohort(years)
        joins=[];where=['n.role=:role'];params={'role':role,'group':group,'sex':gender,'gs':q.min_group_share,'ss':q.min_gender_share}
        weight='n.total';sexshare='NULL';cohort='NULL'
        if group:
            joins.append('JOIN name_group_counts g ON g.name_id=n.id AND g.group_id=:group')
            where.extend(['n.total>0','g.count>0','g.count>=:gs*n.total'])
            weight='g.count'
        if years:
            if gender:
                joins.append('JOIN cohort_counts s ON s.name_id=n.id AND s.sex=:sex')
                where.extend(['s.count>0','s.share>=:ss'])
                sexshare='s.share';cohort='s.count'
            else:
                joins.append('JOIN (SELECT name_id,SUM(count) AS count FROM cohort_counts GROUP BY name_id) s ON s.name_id=n.id')
                where.append('s.count>0');cohort='s.count'
            weight='s.count*(g.count/n.total)' if group else 's.count'
        elif gender:
            joins.append('JOIN name_sex_counts s ON s.name_id=n.id AND s.sex=:sex')
            where.extend(['s.count>0','s.share>=:ss'])
            sexshare='s.share'
            weight=f'({weight})*s.share'
        low,high=bounds
        # Stored length uses indexed source grapheme count. Transform-dependent lengths are filtered below.
        if q.casing=='source' and not q.ascii_only:
            where.append('n.char_length>=:low');params['low']=low
            if high is not None:where.append('n.char_length<=:high');params['high']=high
        if q.use_frequency_weights:where.append(f'({weight})>0')
        sql=f"SELECT n.id,n.name,({weight}) AS weight,({sexshare}) AS gender_share,({cohort}) AS cohort_count FROM names n {' '.join(joins)} WHERE {' AND '.join(where)} ORDER BY n.name"
        entries=[];cumulative=[];mass=0.0
        for row in self.dataset.connection.execute(sql,params):
            rendered=transform(row['name'],q)
            length=char_length(rendered)
            if not rendered or length<low or (high is not None and length>high):continue
            mass+=row['weight'] if q.use_frequency_weights else 1
            entries.append((dict(row),rendered));cumulative.append(mass)
        if len(self._pools)>=48:self._pools.clear()
        result=(entries,cumulative);self._pools[key]=result
        return result

    def _prepare(self,q):
        if q.min_length<0 or (q.max_length is not None and q.max_length<q.min_length):raise ValueError('Invalid inclusive length range')
        if q.gender not in ('auto','female','male','unrestricted'):raise ValueError('Unknown gender')
        if q.max_attempts<1 or not 0<=q.min_group_share<=1 or not 0<=q.min_gender_share<=1:raise ValueError('Invalid attempt limit or share threshold')
        if q.casing not in ('source','upper','lower','title'):raise ValueError('Unknown casing')
        if q.group not in (None,'auto',*GROUPS):raise ValueError('Unknown group')
        if q.birth_year_range and (len(q.birth_year_range)!=2 or q.birth_year_range[0]>q.birth_year_range[1]):raise ValueError('Invalid birth year range')
        template=FORMATS.get(q.format,q.format);fields=[]
        for literal,name,spec,conversion in string.Formatter().parse(template):
            if name is None:continue
            if name.removesuffix('_initial') not in COMPONENTS or spec or conversion:raise ValueError(f'Unsupported field: {name}')
            fields.append(name)
        if not fields:raise ValueError('Format must contain a name placeholder')
        components=tuple(c for c in COMPONENTS if c in fields or c+'_initial' in fields)
        for key,bounds in q.component_lengths.items():
            if key not in components or len(bounds)!=2 or bounds[0]<0 or (bounds[1] is not None and bounds[1]<bounds[0]):raise ValueError('Invalid component bounds')
        pair=tuple(x.upper() for x in q.given_pair) if q.given_pair else None
        if pair and (len(pair)!=2 or not {'given','middle'}.issubset(components)):raise ValueError('given_pair requires two strings and both given and middle slots')
        exception=COMPOUND_EXCEPTIONS.get(pair)
        has_given=any(c in components for c in ('given','middle'))
        genders=['M','F'] if q.gender=='auto' and has_given else [{'male':'M','female':'F'}.get(q.gender) if has_given else None]
        if exception:
            if q.gender in ('male','female') and {'male':'M','female':'F'}[q.gender]!=exception:raise NoCandidates('Requested gender conflicts with compound exception')
            genders=[exception]
        options=[]
        for group in (GROUPS if q.group=='auto' else [q.group]):
            for gender in genders:
                pools={}
                for component in components:
                    role='given' if component in ('given','middle') else 'surname'
                    pool=self._pool(role,group,None if exception and role=='given' else gender,q,q.component_lengths.get(component,(1,None)))
                    if pair and role=='given':
                        matching=[r for r in pool[0] if r[0]['name']==pair[0 if component=='given' else 1]]
                        pool=(matching,[1.0]*len(matching))
                    if not pool[0]:break
                    pools[component]=pool
                else:options.append((group,gender,pools,pools[components[0]][1][-1]))
        if not options:raise NoCandidates('No eligible tokens; relax group, gender, cohort or component limits')
        return template,components,options

    def generate(self,query=None):
        q=query or Query();key=json.dumps(q.__dict__,sort_keys=True)
        if not hasattr(self,'_prepared') or self._prepared[0]!=key:self._prepared=key,self._prepare(q)
        template,components,options=self._prepared[1]
        for _ in range(q.max_attempts):
            group,gender,pools,_=self.random.choices(options,weights=[x[3] for x in options],k=1)[0]
            values={};selected={}
            for component in components:
                rows,cumulative=pools[component]
                row,rendered=rows[bisect.bisect_right(cumulative,self.random.random()*cumulative[-1])]
                selected[component]=(row,rendered)
                values[component]=rendered
                values[component+'_initial']=regex.findall(r'\X',rendered)[0]+('.' if q.initial_period else '')
            text=template.format_map(values);size=char_length(text)
            if size<q.min_length or (q.max_length is not None and size>q.max_length):continue
            details={}
            for component,(row,rendered) in selected.items():
                if row['id'] not in self._records:
                    if len(self._records)>=4096:self._records.clear()
                    self._records[row['id']]=self.dataset.record(row['id'])
                details[component]={**self._records[row['id']],'text':rendered,'selected_gender_share':row['gender_share']}
                if row['cohort_count'] is not None:details[component]['cohort_birth_count']=row['cohort_count']
            return {'text':text,'length':size,'given_names':[selected[c][1] for c in ('given','middle') if c in selected],
                'surnames':[selected[c][1] for c in ('surname','surname2') if c in selected],
                'components':details,'group':group,'compound_exception':bool(q.given_pair and tuple(x.upper() for x in q.given_pair) in COMPOUND_EXCEPTIONS),'gender':{'M':'male','F':'female'}.get(gender,'unrestricted'),
                'birth_year_range':list(q.birth_year_range) if q.birth_year_range else None,
                'use_frequency_weights':q.use_frequency_weights,'generator_version':VERSION,'dataset_version':self.dataset_version}
        raise SamplingExhausted(f'No result within {q.max_attempts} attempts; this does not prove no match exists')
