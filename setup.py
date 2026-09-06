from setuptools import setup, find_packages

setup(
    name="rewind-debug",
    version="0.1.1",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "rewind=rewind.cli:main",
            "rewind-debug=rewind.cli:main",
        ],
    },
)
