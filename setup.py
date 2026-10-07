from io import open

from setuptools import setup, find_packages

with open('README.md', 'r', encoding='utf-8') as f:
    LONG_DESCRIPTION = f.read()

with open('requirements.txt', 'r') as f:
    INSTALL_REQUIRES = f.readlines()

setup(
    name='apply_pr',
    version='3.7.3',
    packages=find_packages(),
    url='https://github.com/gisce/apply_pr',
    project_urls={
        'Documentation': 'https://github.com/gisce/apply_pr#readme',
        'Issues': 'https://github.com/gisce/apply_pr/issues',
        'Releases': 'https://github.com/gisce/apply_pr/releases',
        'Source': 'https://github.com/gisce/apply_pr',
    },
    license='MIT',
    author='GISCE-TI, S.L.',
    author_email='devel@gisce.net',
    description='Apply Pull Requests from GitHub',
    long_description=LONG_DESCRIPTION,
    long_description_content_type='text/markdown',
    python_requires='>=2.7',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Topic :: Software Development :: Version Control :: Git',
        'Topic :: System :: Software Distribution',
    ],
    entry_points='''
        [console_scripts]
        sastre=apply_pr.cli:sastre
        apply_pr=apply_pr.cli:deprecated
    ''',
    install_requires=INSTALL_REQUIRES,
)
