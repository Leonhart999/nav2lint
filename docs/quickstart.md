[中文](quickstart_zh.md) | [ENG](quickstart.md)

# 5-minute quick start

This page is for first-time users. You do not need to know how nav2lint works; just follow the steps.

![nav2lint demo: check, auto-fix, report remaining findings](demo.gif)

## What it does for you

Nav2 parameters are often collected in a YAML file called `nav2_params.yaml`, though a project can use several files and launch-time overrides. A mistake in it often shows up only after `ros2 launch`, buried in a long log. Sometimes there is no error at all, and the parameter just silently has no effect.

nav2lint reads the file before you launch and tells you **which line** has a problem and how to fix it. It does not start ROS and does not touch your robot.

## What you need

- **Python 3.9 or newer.** Ubuntu with ROS 2 already has it.
- **A Nav2 parameter file.** It is usually in the `config/` or `params/` directory of your own package. If you are not sure where it is, run this in a terminal to list the YAML files in your workspace that look like ROS 2 parameter files:

  ```bash
  grep -rl --include=*.yaml ros__parameters ~/ros2_ws/src
  ```

  Replace `~/ros2_ws` with your own workspace directory.

## Step 1: install

**Ubuntu 22.04 (ROS 2 Humble)**, run in a terminal:

```bash
sudo apt update
sudo apt install python3-pip
python3 -m pip install --user "nav2lint @ https://github.com/Leonhart999/nav2lint/archive/refs/tags/v0.3.1.zip"
```

**Ubuntu 24.04 (ROS 2 Jazzy)** does not let pip install packages into the system Python (you get `externally-managed-environment`). Use pipx instead:

```bash
sudo apt update
sudo apt install pipx
pipx install "nav2lint @ https://github.com/Leonhart999/nav2lint/archive/refs/tags/v0.3.1.zip"
pipx ensurepath
```

**Close the terminal and open a new one**, then check the installation:

```bash
nav2lint --version
```

If you see `nav2lint 0.3.1`, it is installed. If you get `command not found`, see [Common problems](#common-problems) below.

## Step 2: find your ROS 2 version

nav2lint needs to know which ROS 2 distro you use, because parameter syntax differs between versions. Run:

```bash
ls /opt/ros
```

It shows installed distro names such as `humble` or `jazzy`. If several are listed, use the one your project actually runs with; `printenv ROS_DISTRO` shows the distro sourced in the current terminal, or nothing if no ROS environment is sourced. nav2lint accepts `humble`, `jazzy`, `kilted`, and `rolling`.

## Step 3: check

Go to the directory that contains your parameter file, then run the check. The example uses `~/ros2_ws/src/my_robot/config`; use your own directory and file name:

```bash
cd ~/ros2_ws/src/my_robot/config
nav2lint --distro humble nav2_params.yaml
```

## Step 4: read the result

The output below comes from the deliberately broken [demo configuration](../examples/quickstart_humble.yaml). You can download it to a scratch directory, name it `nav2_params.yaml`, and run Step 3 to reproduce the example. Your own file will produce different findings.

```
nav2_params.yaml:3: warning[S307] amcl.min_particles=500 is greater than max_particles=200
nav2_params.yaml:12: error[E102] `inflation_layer.inflation_radius` should be float but is int; Nav2 will fail with a parameter type mismatch
    write 1.0
1 error, 1 warning, 0 info; 1 fixable with --fix
```

Taking the second finding apart:

| Part | Meaning |
|---|---|
| `nav2_params.yaml:12` | File name and **line number**: the problem is on line 12 |
| `error` | Severity, see the table below |
| `[E102]` | Rule ID, for looking up details |
| `` `inflation_layer.inflation_radius` should be float but is int `` | The problem: this parameter needs a decimal number, but you wrote an integer |
| `write 1.0` (the indented line) | How to fix it: write `1.0` |

The last line is the summary: 1 error and 1 warning, and 1 of them can be fixed automatically.

**What the severities mean:**

| Severity | Meaning | Do I need to fix it? |
|---|---|---|
| `error` | A detected problem may prevent startup, node configuration, or parameter loading | **Review first**, confirm against the target version, then correct it |
| `warning` | A possible typo, migration issue, or inconsistent setting; it may also be intentional | Review each one |
| `info` | Context to help review; hidden by default | Read when relevant |

These are static checks, not guarantees about runtime behavior. No findings does not mean navigation is safe or correctly tuned.

**Don't understand a finding?** Look up its rule ID:

```bash
nav2lint --explain E102
```

> About `T404` (parameter not in the bundled tables): the parameter is not recorded for this scope and distro in nav2lint's bundled tables. This is not proof that it is absent from the Nav2 sources or ignored at runtime. Possible causes include a typo, the wrong scope or distro, or an incomplete table. Check the target version's documentation and parameter evidence before changing or removing it.

## Step 5: fix

Some problems have exactly one correct fix, and nav2lint can apply it for you. **Preview** the changes first; this does not modify the file:

```bash
nav2lint --distro humble --diff nav2_params.yaml
```

Lines starting with `-` are the original lines, lines starting with `+` are the new ones. When they look right, apply them:

```bash
nav2lint --distro humble --fix nav2_params.yaml
```

Fix the remaining problems yourself: open the file and go to the reported line numbers. Then run Step 3 again until the summary shows `0 error`.

Tip: commit with git or make a backup copy first, so you can always undo a change.

## Check a whole workspace

Instead of naming each file, give a directory. nav2lint finds the Nav2 parameter files in it:

```bash
nav2lint --distro humble ~/ros2_ws/src
```

## Common problems

**`nav2lint: command not found`**
The next step depends on how you installed it:

- **pipx:** run `pipx list` to check that nav2lint is installed, then run `pipx ensurepath` and open a new terminal. A pipx environment is isolated: the system's `python3 -m nav2lint` is not a substitute.
- **pip with `--user`:** run `python3 -m nav2lint --version` with the same Python used for installation. If that works, the package is installed but its command directory is missing from PATH. On Ubuntu the default is `~/.local/bin`; run `export PATH="$HOME/.local/bin:$PATH"` for the current terminal and add that line to `~/.bashrc` if you use Bash.

**`python: command not found`**
On Ubuntu, type `python3`, not `python`.

**`error: externally-managed-environment`**
Your Python environment is managed by the operating system (common on Ubuntu 24.04 and newer). Use pipx as in Step 1 rather than bypassing the protection with `--break-system-packages`.

**`could not detect the distro ... use --distro to set it`**
nav2lint could not work out your ROS 2 version on its own. Find it as in Step 2 and add `--distro humble` (or `jazzy`, etc.) to the command.

**`no Nav2 parameter files found`**
No Nav2 parameter file was found in the directory you gave. Check the directory, or name the file directly.

**`cannot read: ... No such file or directory`**
The file path is wrong. Use `ls` to make sure the file is in the current directory, or give the full path.

**A `/path/to/...` command from the docs fails**
That is a placeholder. Replace it with the real path on your computer.

## Next steps

- Check while you edit in VS Code: see [the VS Code section of the README](../README.md#vs-code).
- Stop typing `--distro` every time: create a `.nav2lint.yaml` in your workspace root containing the line `distro: humble`.
- Every option and rule in detail: see the [README](../README.md).
