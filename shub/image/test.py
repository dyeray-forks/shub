import click
from shub.deploy import list_targets

from shub import exceptions as shub_exceptions
from shub.config import load_shub_config
from shub.image import utils

SHORT_HELP = "Test a built image with Scrapy Cloud contract"
HELP = """
A command to test an image after build step to make sure it fits contract.

It consists of the following steps:

1) check that image exists on local machine
2) check that image has scrapinghub-entrypoint-scrapy python package
3) check that image has start-crawl entrypoint
4) check that image has list-spiders entrypoint

These entrypoints are provided by scrapinghub-entrypoint-scrapy package,
so the goal of the last checks is to validate the package version.

If any of the checks fails - the test command fails as a whole. By default,
the test command is also executed automatically as a part of build command
in its end (if you do not provide --skip-tests parameter explicitly).
"""

SH_EP_SCRAPY_WARNING = \
    'You should add scrapinghub-entrypoint-scrapy(>=0.7.0) dependency' \
    ' to your requirements.txt or to Dockerfile to run the image with' \
    ' Scrapy Cloud.'


@click.command(help=HELP, short_help=SHORT_HELP)
@click.argument("target", required=False, default="default")
@click.option("-l", "--list-targets", help="list available targets",
              is_flag=True, is_eager=True, expose_value=False,
              callback=list_targets)
@click.option("-d", "--debug", help="debug mode", is_flag=True)
@click.option("--version", help="release version")
def cli(target, debug, version):
    test_cmd(target, version)


def test_cmd(target, version):
    config = load_shub_config()
    image = config.get_image(target)
    version = version or config.get_version()
    image_name = utils.format_image_name(image, version)
    docker_client = utils.get_docker_client()
    for check in [_check_image_exists,
                  _check_start_crawl_entry,
                  _check_list_spiders_entry,
                  _check_sh_entrypoint]:
        check(image_name, docker_client)


def _check_image_exists(image_name, docker_client):
    """Check that the image exists on local machine."""
    # if there's no docker lib, the command will fail earlier
    # with an exception when getting a client in get_docker_client()
    from docker.errors import NotFound
    try:
        docker_client.inspect_image(image_name)
    except NotFound as exc:
        utils.debug_log("{}".format(exc))
        raise shub_exceptions.NotFoundException(
            "The image doesn't exist yet, please use build command at first.")


def _check_sh_entrypoint(image_name, docker_client):
    """Check that the image has scrapinghub-entrypoint-scrapy pkg"""
    status, logs = _run_docker_command(
        docker_client, image_name, ['pip', 'show', 'Scrapy'])
    # doesn't make sense to check sh-ep-scrapy if there's no Scrapy
    if status == 0 and logs:
        status, logs = _run_docker_command(
            docker_client, image_name,
            ['pip', 'show', 'scrapinghub-entrypoint-scrapy'])
        if status != 0 or not logs:
            raise shub_exceptions.NotFoundException(SH_EP_SCRAPY_WARNING)


def _check_list_spiders_entry(image_name, docker_client):
    """Check that the image has list-spiders entrypoint"""
    status, logs = _run_docker_command(
        docker_client, image_name, ['which', 'list-spiders'])
    if status != 0 or not logs:
        raise shub_exceptions.NotFoundException(
            "list-spiders command is not found in the image.\n"
            "Please upgrade your scrapinghub-entrypoint-scrapy(>=0.7.0)")


def _check_start_crawl_entry(image_name, docker_client):
    """Check that the image has start-crawl entrypoint"""
    status, logs = _run_docker_command(
        docker_client, image_name, ['which', 'start-crawl'])
    if status != 0 or not logs:
        raise shub_exceptions.NotFoundException(
            "start-crawl command is not found in the image.\n"
            + SH_EP_SCRAPY_WARNING)


def _run_docker_command(client, image_name, command):
    """A helper to execute an arbitrary cmd with given docker image"""
    container = client.create_container(image=image_name, command=command)
    try:
        client.start(container)
        statuscode = client.wait(container=container['Id'])
        logs = client.logs(container=container['Id'], stdout=True,
                           stderr=True if statuscode else False,
                           stream=False, timestamps=False)
        utils.debug_log("{} results:\n{}".format(command, logs))
        return statuscode, logs
    finally:
        client.remove_container(container)
