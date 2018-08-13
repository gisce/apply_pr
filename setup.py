from setuptools import setup, find_packages


setup(
    name='apply_pr',
    version='1.5.1',
    packages=find_packages(),
    url='https://github.com/gisce/apply_pr',
    license='MIT',
    author='GISCE-TI, S.L.',
    author_email='devel@gisce.net',
    description='Apply Pull Requests from GitHub',
    entry_points='''
        [console_scripts]
        sastre=apply_pr.cli:tailor
        tailor=apply_pr.cli:tailor
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
