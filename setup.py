from setuptools import setup, find_packages


setup(
    name='apply_pr',
    version='0.1.0',
    packages=find_packages(),
    url='https://github.com/gisce/apply_pr',
    license='MIT',
    author='GISCE-TI, S.L.',
    author_email='devel@gisce.net',
    description='Apply Pull Requests from GitHub',
    entry_points='''
        [console_scripts]
        apply_pr=apply_pr.cli:apply_pr
    ''',
    install_requires=[
        'fabric',
        'osconf',
        'python-slugify',
        'requests',
        'click'
    ]
)
