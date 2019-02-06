import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="yachat-carlosgavso",
    version="0.0.1",
    author="Jose Carlos Martinez Garcia-Vaso",
    author_email="carlosgvaso@utexas.edu",
    description="YatChat server-client chat app.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pypa/sampleproject",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
