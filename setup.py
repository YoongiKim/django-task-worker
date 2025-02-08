from setuptools import setup, find_packages

setup(
    name="django-simple-task-worker",
    version="0.1.0",
    description="Task worker for Django using Redis and database-based queues",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Yoongi Kim",
    author_email="yoongi@yoongi.kim",
    url="https://github.com/YoongiKim/django-simple-task-worker",
    license="Apache License 2.0",  # Updated license to Apache License 2.0
    packages=find_packages(exclude=["tests", "*.tests", "*.tests.*", "tests.*"]),
    include_package_data=True,
    install_requires=[
        "Django>=3.2",
        "redis>=4.5.0",
        "stopit>=1.1.2",
    ],
    classifiers=[
        "Framework :: Django",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
    entry_points={
        "console_scripts": [
            "run-worker = worker.management.commands.run_worker:Command.handle",
        ],
    },
)
