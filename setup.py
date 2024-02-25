from setuptools import setup, find_packages

# Read dependencies from requirements.txt
with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name='aidrin',
    version='0.1.0',
    author='Kaveen Hiniduma',
    author_email='hiniduma.1@osu.edu',
    description='A tool to help evaluate your data for AI/ML projects',
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        'console_scripts': [
            'aidrin=aidrin.app:main',
        ],
    },
)