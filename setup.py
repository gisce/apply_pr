from setuptools import setup, find_packages


setup(
    name='apply_pr',
    version='1.8.3',
    packages=find_packages(),
    url='https://github.com/gisce/apply_pr',
    license='MIT',
    author='GISCE-TI, S.L.',
    author_email='devel@gisce.net',
    description='Apply Pull Requests from GitHub',
    entry_points='''
        [console_scripts]
        apply_pr=apply_pr.cli:apply_pr
        get_deploys=apply_pr.cli:get_deploys
        status_pr=apply_pr.cli:status_pr
        check_prs_status=apply_pr.cli:check_prs_status
        create_changelog=apply_pr.cli:create_changelog
    ''',
    install_requires=[
        'fabric<2.0',
        'osconf',
        'python-slugify',
        'requests',
        'click',
        'tqdm'
    ]
)
