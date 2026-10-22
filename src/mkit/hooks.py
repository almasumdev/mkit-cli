"""Project hooks: a project's own scripts, run at fixed points of a pipeline.

    [hooks]
    pre_deploy  = "python console/check.py"
    post_build  = "console/sign_extra.sh"
    post_deploy = "python console/deploy_backend.py"

A hook runs in the project root with MKIT_VERSION_NAME / MKIT_VERSION_CODE /
MKIT_DRY_RUN set. A non-zero exit fails the step it belongs to, like any other
step. The command is split like a shell would, but runs without a shell.
"""
import os
import shlex

from . import proc

POINTS = ('pre_deploy', 'post_build', 'post_deploy', 'post_promote')


def get(ctx, point):
    return ctx.project.section('hooks').get(point)


def run(ctx, point, **env_values):
    command = get(ctx, point)
    if not command:
        return None
    argv = shlex.split(command, posix=os.name != 'nt')
    env = dict(os.environ, MKIT_DRY_RUN='1' if ctx.dry_run else '0',
               **{f'MKIT_{k.upper()}': str(v) for k, v in env_values.items()})
    proc.stream(argv, f'hook {point}', lambda line: bool(line.strip()), cwd=ctx.project.root, env=env)
    return command
