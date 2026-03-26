from pathlib import Path

from setuptools import find_packages, setup

README = Path(__file__).with_name("README.md").read_text(encoding="utf-8")

setup(
    name="atb-cli",
    version="0.3.0",
    description="Versioned, reproducible CLI tooling for querying ATB parquet releases",
    long_description=README,
    long_description_content_type="text/markdown",
    author="OpenAI",
    python_requires=">=3.10",
    packages=find_packages(include=["atb_cli", "atb_cli.*"]),
    include_package_data=True,
    install_requires=[
        "click>=8.1",
        "pandas>=2.0",
        "pyarrow>=14.0",
        "requests>=2.31",
        "tomli>=2.0; python_version < '3.11'",
    ],
    extras_require={
        "test": ["pytest>=7.0"],
    },
    entry_points={
        "console_scripts": [
            "atb=atb_cli.cli:main",
        ]
    },
)
