"""tessera's command-line interface."""

from __future__ import annotations

import asyncio
import logging

import click

from . import __version__
from .config import load_config
from .jobs import JobRunner, dumps_summary, summarize_log
from .serving import StartupError


@click.group()
@click.version_option(__version__)
@click.option("-v", "--verbose", is_flag=True, help="Log what tessera is doing.")
def cli(verbose):
    """Run batches of prompts against model servers within a token budget."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


@cli.command()
@click.argument("job_file", type=click.Path(exists=True, dir_okay=False))
def run(job_file):
    """Run the job in JOB_FILE."""
    config = load_config(job_file)
    try:
        summary = asyncio.run(JobRunner(config).run())
    except StartupError as e:
        raise click.ClickException(str(e))
    click.echo(f"{summary.name}: {summary.ok} ok, {summary.failed} failed; results in {summary.output}, log in {summary.log_path}")


@cli.command()
@click.argument("job_file", type=click.Path(exists=True, dir_okay=False))
def serve(job_file):
    """Start the model servers of JOB_FILE, wait until they are ready, then stop them (a startup check)."""
    config = load_config(job_file)
    if not config.server.command:
        raise click.ClickException("the job file has no server.command")

    async def check():
        servers = await JobRunner(config).start_servers()
        for server in servers:
            await server.stop()
        return len(servers)

    try:
        count = asyncio.run(check())
    except StartupError as e:
        raise click.ClickException(str(e))
    click.echo(f"{count} model server(s) started and were ready")


@cli.command(name="log")
@click.argument("log_file", type=click.Path(exists=True, dir_okay=False))
def log_command(log_file):
    """Summarize a run log."""
    click.echo(dumps_summary(summarize_log(log_file)))
