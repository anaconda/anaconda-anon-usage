# anaconda-anon-usage

## Simple, anonymous telemetry for conda

This package augments the request header data that
[`conda`](https://docs.conda.io/) delivers to package
servers during index and package requests. Specifically,
three randomly generated tokens are appended to the
"user agent" that Conda already sends with each request.

These tokens are designed to reveal _no_
personally identifying information. And yet, they enable
Anaconda to better disaggregate individual user patterns
from our access logs. Use cases include:

- Counting the number of conda clients on a network
- Providing more accurate estimates of package popularity
- Other statistical analyses of conda usage patterns;
  e.g., environment count, frequency of updates, etc.

This package is installed as a dependency of certain
Anaconda-branded packages, such as Navigator. While we
ask that you allow us to gather this data to help us
improve our user experience, the additional behavior
can still be disabled with a single `conda config`.

### Installation

You will likely not need to install `anaconda-anon-usage`
yourself, as it will come as a dependency of other Anaconda
packages such as `anaconda-navigator`. Nevertheless, it can
readily be installed as follows:
```
conda install -n base anaconda-anon-usage
```
This package has no additional dependencies other than `conda`
itself. It employs a [conda pre-command plugin](https://docs.conda.io/projects/conda/en/latest/user-guide/concepts/conda-plugins.html) to
modify the user agent string.

### Explaining the behavior

The easiest way to verify that it is
engaged is by typing `conda info` and examining the `user-agent`
line. The user-agent string will look something like this
(split over two lines for readability):

```
conda/22.11.1 requests/2.28.1 CPython/3.10.4 Darwin/22.2.0
OSX/13.1 aau/0.1.0 c/sgzzP8ytS_aywmqkDTJ69g s/3ItHH93LRUmCoJZkMOiD3g e/hCmim1vFSbinlm4waR6dZw
a/6NxsCXJLQ-uoMUBAZmGsTQ
```

The first five tokens constitute the standard user-agent string
that conda *normally* sends with HTTP requests, and are similar
to what a standard web browser such as Chrome, Safari, or Edge
send every time a page is requested. The last five tokens, however,
are generated by `anaconda-anon-usage` package:

- The version of the `anaconda-anon-usage` package.
- A *client token* `sgzzP8ytS_aywmqkDTJ69g` is generated once by the
  conda client and saved in the `~/.conda` directory, so that
  the same value is delivered as long as that
  directory is maintained.
- A *session token* `s/3ItHH93LRUmCoJZkMOiD3g` is generated afresh every time
  `conda` is run.
- An *environment token* `e/hCmim1vFSbinlm4waR6dZw` generated uniquely for
  each separate conda environment (`-n <name>` or `-p <prefix>`).
- An *Anaconda cloud token* `a/6NxsCXJLQ-uoMUBAZmGsTQ` that encodes the user
  ID of a user that is logged into Anaconda Cloud. If the user is not
  logged in, this token will not be present.

Here is an easy way to see precisely what is being shipped to the
upstream server on Unix:

```
conda clean --index --yes
conda search -vvv fakepackage 2>&1 | grep 'User-Agent'
```

This produces an output like this:

```
> User-Agent: conda/22.11.1 requests/2.28.1 CPython/3.10.4 Darwin/22.2.0 OSX/13.1 aau/0.1.0 c/sgzzP8ytS_aywmqkDTJ69g s/3ItHH93LRUmCoJZkMOiD3g e/hCmim1vFSbinlm4waR6dZw
```

### Anonymous token design

These standard three tokens are design to ensure that they do not
reveal identifying information about the user or the host. Specifically:

- Each token is generated from a [`uuid4`](https://docs.python.org/3/library/uuid.html#uuid.uuid4)
  which uses [`os.urandom`](https://docs.python.org/3/library/os.html#os.urandom)
  data and is encoded with [base64](https://docs.python.org/3/library/base64.html#base64.urlsafe_b64encode)
  in an URL safe output.
- The client token is saved in `~/.conda/aau_token`, so that
  it can be read with every `conda` command. If for some reason the
  token cannot be created or read, the `c/` token will be omittted.
- Similarly, the environment token is saved in
  `$CONDA_PREFIX/etc/aau_token`, so it can be read with every
  `conda` command applied to that environment. If for some reason the
  token cannot be created or read, the `e/` token will be omitted.

In short, these tokens were design so that they cannot be used
to recover an underlying username, hostname, or
environment name. The underlying purpose of these tokens is
*disaggregation*: to distinguish between different users,
sessions, and/or environments for analytics purposes. This
works because the probability that two different
users will produce the same tokens is vanishingly small.

### Disabling

Because this package is delivered as a dependency of other Anaconda
packages, you may not be able to remove it from your conda environment.
You may, however, disable the delivery of the three tokens

```
conda config --set anaconda_anon_usage off
```
(`false` or `no` may also be used). With this setting in place,
the additional tokens will be removed; e.g.

```
user-agent : conda/22.11.1 requests/2.28.1 CPython/3.10.4 Darwin/22.2.0 OSX/13.1 aau/0.1.0
```

To re-enable it, you may use the command
```
conda config --set anaconda_anon_usage on
```
(`true` or `yes` may also be used).

## Advanced usage

Starting with version 0.6.0, `anaconda-anon-usage` has included capabilities
intended to enable organizations to enhance the telemetry generated by this
module to more precisely track their organization's usage.

It is important to note that these additional capabilities are off by
default, and are only enabled when taking deliberate steps, usually
by a system administrator. For a typical Anaconda user, therefore,
nothing in this section applies.

### Organization and machine tokens

This module now supports two additional token types that must be manually
installed on a user's machine. Typically this will be accomplished by a
system administrator, sometimes using a mobile device management tool.

- An _organization_ token, prefixed with `o/`, is intended to help identify
  groups of conda installations owned by the same organization.
- A _machine_ token, prefixed with `m/`, is intended to provide a unique
  machine ID without revealing private hostname information.

To enable these tokens, the following files should be created in a
standard conda configuration directory; we recommend `/etc/conda/`
on Unix/macOS and `C:\ProgramData\conda\` on Windows:

- `org_token`: the organization token. This value should be identical for
  all machines within the same organization.
- `machine_token`: the machine token. This value should be unique to
  each machine.
- `condarc`: To ensure that the `anaconda-anon-usage` telemetry remains enabled,
  this file should include the following lines:
  ```
  anaconda_anon_usage: true #!final
  aggressive_update_packages: [anaconda-anon-usage]
  ```

For convenience, the `tokens` submodule includes a function to generate
a random token ready for use as an organization or machine token:
```
python -m anaconda_anon_usage.tokens --random
```

### Activation heartbeats

The `anaconda-anon-usage` telemetry provides helpful information when a user installs
a package or searches the package repository. By default, however, it provides no
information about when a user _uses_ a conda environment.

To address that limitation, `anaconda-anon-usage` implements an opt-in
_activation heartbeat_ that is triggered when performing a full `conda` environment
activation; e.g., using `conda activate`. This heartbeat takes the form of a
lightweight `HEAD` request to the upstream repository, and thus includes the
user agent string enhanced by `anaconda-anon-usage`. The heartbeat is run in a
background thread, with a short network timeout, and with all exceptions
swallowed, to ensure that the user's workflow is not disrupted.

This heartbeat functionality is off by default, even when the rest of `anaconda-anon-usage`
is enabled. To enable them, add this additional line to the system `condarc` file
discussed above:
```
anaconda_heartbeat: true #!final
```
