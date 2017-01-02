from setuptools import setup, find_packages


setup(
    name='apply_pr',
    version='1.0.0',
    packages=find_packages(),
    url='https://github.com/gisce/apply_pr',
    license='MIT',
    author='GISCE-TI, S.L.',
    author_email='devel@gisce.net',
    description='Apply Pull Requests from GitHub',
    entry_points='''
        [console_scripts]
        apply_pr=apply_pr.cli:apply_pr
        check_pr=apply_pr.cli:check_pr
        status_pr=apply_pr.cli:status_pr
        check_prs_status=apply_pr.cli:check_prs_status
    ''',
    install_requires=[
        'fabric',
        'osconf',
        'python-slugify',
        'requests',
        'click',
        'tqdm'
    ]
)
