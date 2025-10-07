from setuptools import setup, find_packages
from pathlib import Path

requirements_path = Path(__file__).parent / "requirements.txt"

with open(requirements_path, 'r') as f:
    install_requires = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name='stats_code_analyser',
    version='0.1.0',
    description='Статический анализатор кода Python',
    author='vanechka1437',
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        'console_scripts': [
            'stats_code_analyser = stats_code_analyser.cli:main',
        ]
    },
    install_requires=install_requires,
)
