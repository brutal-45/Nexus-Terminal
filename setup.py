"""
Nexus — An intelligent AI assistant running entirely on the user's local machine.
Operates through the terminal with zero internet dependency for core functionality.

Developed under brutaltools.
"""

from setuptools import setup, find_packages

setup(
    name="nexus",
    version="1.0.0",
    description="Nexus — Local Terminal AI Assistant",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    author="brutaltools",
    python_requires=">=3.10",
    packages=find_packages(),
    install_requires=[
        "rich>=13.0.0",
        "pyyaml>=6.0",
    ],
    extras_require={
        "full": ["orjson>=3.9.0"],
        "dev": ["pytest>=7.0.0", "pytest-cov>=4.0.0"],
    },
    entry_points={
        "console_scripts": [
            "nexus=nexus.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Utilities",
    ],
)
