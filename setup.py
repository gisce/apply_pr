from setuptools import setup, find_packages

with open('requirements.txt', 'r') as f:
    INSTALL_REQUIRES = f.readlines()

setup(
    name='apply_pr',
    version='2.3.0',
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
    install_requires=INSTALL_REQUIRES
)
