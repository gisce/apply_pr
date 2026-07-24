# -*- coding: utf-8 -*-
from __future__ import (
    with_statement, absolute_import, unicode_literals, print_function
)
import requests
import json
import re
import os
from slugify import slugify

from .github_utils import github_config
from requests.exceptions import ConnectionError
import logging
from collections import OrderedDict
from tqdm import tqdm

logger = logging.getLogger(__name__)

SKIP_LABELS = ['internal', 'custom', 'to be merged', 'deployed', 'traduccions']
GAS_LABEL = 'gas'
ELEC_LABEL = u'eléctrico'
OFICINA_VIRTUAL = 'oficinavirtual'
TYPE_LABELS = [ELEC_LABEL, GAS_LABEL, OFICINA_VIRTUAL]
TOP_FEATURE = u':fire: top feature'
COMMON_KEY = u'COMÚN'


def get_label(label_keys, labels, skip_custom=False):
    if not skip_custom:
        for label in labels:
            name = label['name'].lower()
            if name == 'custom':
                return 'custom'
            if name == 'internal':
                return 'internal'
    for label in labels:
        name = label['name'].lower()
        for key in label_keys:
            if key in name:
                return key
    return 'others'


def get_url_image(image, owner, repository):
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': 'Bearer %s' % github_config()['token']
    }
    url = "https://api.github.com/markdown"
    data = {
        'text': '''{image}'''.format(image=image),
        'mode': 'gfm',
        'context': '{owner}/{repository}'.format(owner=owner,
                                                 repository=repository)
    }
    r = requests.api.post(url, headers=headers, json=data)
    if r.status_code >= 200 and r.status_code < 300:
        import re
        text = r.content
        urls = re.findall(
            'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            text)
        if urls:
            return urls[0]
        else:
            return image
    else:
        return image


def print_item_detail(item, owner, repository, key=None):
    def find_all(a_str, sub):
        start = 0
        while True:
            start = a_str.find(sub, start)
            if start == -1: return
            yield start
            start += len(sub)  # use start += 1 to find overlapping matches

    body = item['body'] or ''
    body = re.sub('^# ', '#### ', body).strip()
    body = re.sub('\n# ', '\n#### ', body).strip()
    body = re.sub('^## ', '#### ', body).strip()
    body = re.sub('\n## ', '\n#### ', body).strip()
    body = re.sub(
        '#(\d+)',
        '[:fa-github: \g<1>](https://github.com/{}/{}/pull/\g<1>)'.format(
            owner, repository
        ), body)
    body = re.sub(
        '- #(\d+)',
        '- [:fa-github:  \g<1>](https://github.com/{}/{}/pull/\g<1>)'
        ''.format(
            owner, repository
        ), body)
    ## Search remove parts
    idx = body.find('#### Afectaciones')
    if idx > 0:
        body = body[:idx - 1] + ''
    idx_images = list(find_all(body, '![image]'))
    if idx_images:
        images_to_replace = {}
        for idx_img in idx_images:
            id_end_image = body.find(')', idx_img)
            if id_end_image > 0:
                image = body[idx_img:id_end_image + 1]
                new_url = get_url_image(image, owner, repository)
                new_image = '![image]({})'.format(new_url)
                images_to_replace[image] = new_image
        for image, new_image in images_to_replace.items():
            body = body.replace(image, new_image)

    label = ''
    if key:
        for l in item['labels']:
            if l['name'] not in SKIP_LABELS:
                label += u' <span class="label" ' \
                         u'style="background-color: #{color};">{name}</span>'.format(
                    name=l['name'],
                    color=l['color'])
            label = '\n' + label
    message = (
        u'\n\n### {title} [:fa-github: {number}]({url})  {label}\n\n{body}\n ---'.format(
            title=item['title'], number=item['number'],
            url=item['url'], body=body, label=label
        )
    )
    return message


def print_item(item, milestone):
    title_anchor = slugify(item['title'])
    message = u'\n* {title} [:fa-plus-circle: detalles](../detailed_{milestone}#{title_anchor}-{number}) - [:fa-github: {number}]({url})'.format(
        title=item['title'], number=item['number'], url=item['url'],
        milestone=milestone, title_anchor=title_anchor
    )
    return (message)


def get_pulls(url):
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    # NO GIS NO FACT
    r = requests.get(url, headers=headers)
    pull = json.loads(r.text)
    total_prs = pull['total_count']
    pulls_items = []
    total_fetch = 0
    page = 1
    while total_fetch < total_prs:
        items = pull.get('items', None)
        if items is None:
            break
        # pprint.pprint(items)
        total_fetch += len(items)
        pulls_items += items
        if total_fetch >= total_prs:
            break
        page += 1
        new_url = url + "&page={}".format(page)
        r = requests.get(new_url, headers=headers)
        pull = json.loads(r.text)
    return pulls_items



def make_changelog(
        milestone, show_issues=False, changelog_path='/tmp',
        owner='gisce', repository='erp'):
    import copy
    if not os.path.exists(changelog_path):
        os.makedirs(changelog_path)
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': 'Bearer %s' % github_config()['token']
    }
    pulls_items = []
    logger.info('Getting PRs from GitHub')
    # NO GIS NO FACT
    url = ("https://api.github.com/search/issues"
           "?q=is:pr+is:merged+milestone:{milestone}+repo:{owner}/{repository}+-label:internal+-label:custom+-label:GIS+-label:facturacio"
           "&type=pr"
           "&sort=create"
           "d&order=asc"
           "&per_page=250").format(
        milestone=milestone, owner=owner, repository=repository
    )
    pulls_no_gis_no_fact = get_pulls(url)
    print('Total PRs no GIS no Fact: {}'.format(len(pulls_no_gis_no_fact)))
    pulls_items.extend(pulls_no_gis_no_fact)
    url = ("https://api.github.com/search/issues"
           "?q=is:pr+is:merged+milestone:{milestone}+repo:{owner}/{repository}+-label:internal+-label:custom+label:GIS+-label:facturacio"
           "&type=pr"
           "&sort=create"
           "d&order=asc"
           "&per_page=100").format(
        milestone=milestone, owner=owner, repository=repository
    )
    pulls_gis_no_fact = get_pulls(url)
    print('Total PRs GIS no Fact: {}'.format(len(pulls_gis_no_fact)))
    pulls_items.extend(pulls_gis_no_fact)
    url = ("https://api.github.com/search/issues"
           "?q=is:pr+is:merged+milestone:{milestone}+repo:{owner}/{repository}+-label:internal+-label:custom+-label:GIS+label:facturacio"
           "&type=pr"
           "&sort=create"
           "d&order=asc"
           "&per_page=100").format(
        milestone=milestone, owner=owner, repository=repository
    )
    pulls_no_gis_fact = get_pulls(url)
    print('Total PRs no GIS no Fact: {}'.format(len(pulls_no_gis_fact)))
    pulls_items.extend(pulls_no_gis_fact)
    isses_desc = []
    top_pulls = []
    pulls_desc = OrderedDict(
        [
            ('custom', []),
            ('internal', []),
            ('bug', []),
            ('core', []),
            ('atr', []),
            ('telegestio', []),
            ('gis', []),
            ('facturacio', []),
            ('medidas', []),
            ('others', []),
            ('traduccions', []),

        ]
    )
    pulls_sep = {
        GAS_LABEL: copy.deepcopy(pulls_desc),
        ELEC_LABEL: copy.deepcopy(pulls_desc),
        OFICINA_VIRTUAL: copy.deepcopy(pulls_desc),
        'others': copy.deepcopy(pulls_desc)
    }
    label_keys = list(pulls_desc.keys())
    other_desc = []
    changelog_file = 'changelog_{}.md'.format(milestone)
    top_file = 'top_{}.md'.format(milestone)
    detailed_file = 'detailed_{}.md'.format(milestone)
    print('Total PRs: {}'.format(len(pulls_items)))
    number = 0
    for item in tqdm(pulls_items):
        url_item = item['html_url']
        item_info = {
            'title': item['title'],
            'number': item['number'],
            'url': url_item,
            'body': item['body'],
            'labels': item['labels'],
        }
        if 'issues' in url_item:
            isses_desc.append(item_info)
        elif 'pull' in url_item:
            p_url = "https://api.github.com/repos/{owner}/{repository}/pulls/{number}".format(
                owner=owner, repository=repository, number=item_info['number']
            )
            try:
                r = requests.get(p_url, headers=headers)
                pull_desc = json.loads(r.text)
                item_info['pull_info'] = pull_desc
                branch = pull_desc['base']['ref']
            except ConnectionError as e:
                tqdm.write(
                    'Failed to get infor for  {}'.format(item_info['number']))
                branch = 'developer'

            if branch != 'developer':
                continue
            type_key = get_label(TYPE_LABELS, item['labels'], skip_custom=True)
            top = get_label([TOP_FEATURE], item['labels'], skip_custom=True)
            if TOP_FEATURE.lower() in top:
                top_pulls.append(item_info)
            key = get_label(label_keys, item['labels'])
            pulls_sep[type_key][key].append(item_info)
        else:
            other_desc.append(item_info)
        number += 1
    logger.info('Total imported: {}'.format(number))
    pulls_sep[GAS_LABEL].pop('custom')
    pulls_sep[ELEC_LABEL].pop('custom')
    pulls_sep[GAS_LABEL].pop('internal')
    pulls_sep[ELEC_LABEL].pop('internal')
    pulls_sep[ELEC_LABEL].pop('traduccions')
    pulls_sep[GAS_LABEL].pop('traduccions')
    for key in ['gis', 'telegestio', 'medidas', 'facturacio']:
        pulls_sep[ELEC_LABEL][key] += pulls_sep['others'][key]
        pulls_sep['others'][key] = []
    pulls_sep['others'].pop('custom')
    pulls_sep['others'].pop('traduccions')
    pulls_sep['others'].pop('internal')
    pulls_sep[COMMON_KEY] = pulls_sep.pop('others')
    index_bug = label_keys.index('bug')
    label_keys.pop(index_bug)
    label_keys.append('bug')

    # TOP FEATURES
    logger.info('Writting top feature on {}/:'.format(changelog_path))
    with open('{}/{}'.format(changelog_path, top_file), 'w') as f:
        f.write(
            "# TOP FEATURES version {milestone}\n".format(milestone=milestone))
        for pull in top_pulls:
            f.write(print_item(pull, milestone))

    # CHANGELOGS
    logger.info('Writting changelog on {}/:'.format(changelog_path))
    with open('{}/{}'.format(changelog_path, changelog_file), 'w') as f:
        f.write("# Changelog version {milestone}\n".format(milestone=milestone))
        for type_l in TYPE_LABELS + [COMMON_KEY]:
            f.write('\n## {key}\n'.format(key=type_l.upper()))
            for key in label_keys:
                pulls = pulls_sep[type_l].get(key, [])
                if pulls:
                    f.write('\n### {key}\n'.format(key=key.upper()))
                    for pull in pulls:
                        f.write(print_item(pull, milestone))
        if show_issues:
            f.write('\n# Issues:  \n')
            for issue in isses_desc:
                f.write(print_item(issue, milestone))
        if other_desc:
            f.write('\n# Others :  \n')
            for pull in other_desc:
                f.write(print_item(pull, milestone))
    logger.info('    {}/{}'.format(changelog_path, changelog_file))
    with open('{}/{}'.format(changelog_path, detailed_file), 'w') as f:
        f.write("# Detalles version {milestone}\n".format(milestone=milestone))
        for type_l in TYPE_LABELS + [COMMON_KEY]:
            f.write('\n## {key}\n'.format(key=type_l.upper()))
            for key in label_keys:
                pulls = pulls_sep[type_l].get(key, [])
                if pulls:
                    f.write('\n### {key}\n'.format(key=key.upper()))
                    for pull in tqdm(pulls,
                                     desc=' Generating info {} - {}'.format(
                                             type_l.upper(), key)):
                        f.write(
                            print_item_detail(pull, owner, repository, key=key))
        if show_issues:
            logger.info('\n# Issues:  \n')
            for issue in isses_desc:
                f.write(print_item_detail(issue, owner, repository, key=key))
        if other_desc:
            print('\n# Others :  \n')
            for pull in tqdm(other_desc,
                             desc=' Generating info for OTHER INFO'):
                f.write(print_item_detail(pull, owner, repository, key=key))
    logger.info('    {}/{}'.format(changelog_path, detailed_file))
    return True
