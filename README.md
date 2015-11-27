## Apply pull requests

Fabric tools to apply pull requests in servers using `git format-patch` and
`git am`.
Is integrated with the new [deployment
API](https://developer.github.com/v3/repos/deployments/) from GitHub.

To use you to [generate a OAuth token](https://github.com/settings/tokens/new)
from GitHub and set to the `GITHUB_TOKEN` environment variable.

HOW TO: Apply pull requests
===========================

**NOTE**: do not include braces on the following commands

1. Download apply_pr repository and move to apply_pr directory
2. If fabric is not installed, switch to a virtualenv and run: `pip install fabric`
3. Run the following command:

    `$ fab-f ../apply_pr/fabfile.py apply_pr:{pull request number} -H fabric@{client}.erp.clients`

4. If previous command returns an error:

    `$ export GITHUB_TOKEN={your personal token}`

5. Run step 3 again
6. Connect to client server with SSH
7. Login as root
8. Restart the server running the following commands:

    ```sh
    $ supervisor ctl
    $ status (now we can see the names of the servers to be restarted)
    $ restart {server name 1} {server name 2} ...
    ```
