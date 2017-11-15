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

1. Install apply_pr

    `$ pip install apply_pr`

2. Export your GitHub Token

    `$ export GITHUB_TOKEN={your personal token}`

3. Run the following command:

    `$ apply_pr --pr {pull request number} --host=ssh://user:password@host`
    
    PS: Remember to include the `sitecustomize.py` inside pypath as a workaround in order to use it:
    ``` 
    $ wget https://github.com/gisce/erp/blob/developer/server/sitecustomize/sitecustomize.py?raw=true -O $VIRTUAL_ENV/lib/python2.7/sitecustomize.py
    ``` 
6. Connect to client server with SSH
7. Login as root
8. Restart the server running the following commands:

    ```sh
    $ sudo supervisorctl
    $ status (now we can see the names of the servers to be restarted)
    $ restart {server name 1} {server name 2} ...
    ```
9. ```$ tail -f {server name}``` Check server status after restart
