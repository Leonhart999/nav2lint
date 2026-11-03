# nav2lint 使用说明书

nav2lint 是 ROS 2 Nav2 参数文件（`nav2_params.yaml`）的静态检查工具。它在启动 Nav2 之前读一遍 YAML，找出会导致启动失败、参数被悄悄忽略、或者导航表现异常的写法，并给出行号和修改建议。

它不依赖 ROS，不会启动任何节点。普通检查和查询不修改文件；`--fix` 会修改参数文件，`--init-vscode` 会创建或合并任务配置。

---

## 1. 安装

### 1.1 WSL / Ubuntu（装了 ROS 2 的环境）

ROS 2 自带的 python3 已经有 PyYAML，不用安装，直接从源码运行：

```bash
PYTHONPATH=/mnt/d/projects/nav2lint/src python3 -m nav2lint --version
```

建议加一个 alias，以后在任何目录都能直接用：

```bash
echo 'alias nav2lint="PYTHONPATH=/mnt/d/projects/nav2lint/src python3 -m nav2lint"' >> ~/.bashrc
source ~/.bashrc
```

### 1.2 Windows

项目目录下已经有一个虚拟环境 `.venv`，在 CMD 或 PowerShell 里运行：

```bat
D:\projects\nav2lint\.venv\Scripts\nav2lint --version
```

要在别的 Python 环境里安装，进入项目目录执行 `pip install -e .`。

> 注意：Windows 的 `.venv` 不能在 WSL 里用；反过来也一样。在 WSL 的 bash 里，路径要写成 `/mnt/d/...`，不能写 `D:\...`。

---

## 2. 快速上手

第一次接触 nav2lint、对命令行也不太熟的话，建议先看 [5 分钟上手](quickstart_zh.md)，里面从安装到看懂结果一步步讲。

```bash
nav2lint --distro humble ~/ros2_ws/src/lidar_nav/config/nav2_params_sim.yaml
```

输出示例：

```
nav2_params.yaml:26: error[E102] `inflation_layer.inflation_radius` should be float but is int; Nav2 will fail with a parameter type mismatch
    write 1.0
nav2_params.yaml:33: warning[S303] `voxel_layer.scan` raytrace_max_range=2.0 is less than obstacle_max_range=3.0; obstacles marked between 2.0 and 3.0 m are never cleared
1 error, 1 warning, 0 info
```

每条结果的格式是：

```
文件:行号: 级别[规则编号] 问题描述
    修改建议（不一定每条都有）
```

最后一行是汇总。没有任何问题时只输出 `0 error, 0 warning, 0 info`。

推荐用法：每次改完参数文件、`ros2 launch` 之前跑一次。

---

## 3. 命令行参数

```
nav2lint [选项] 文件或目录 [文件或目录 ...]
```

| 选项 | 作用 |
|---|---|
| `--distro {auto,humble,jazzy,kilted,rolling}` | 目标发行版。不写时先看配置文件 `.nav2lint.yaml`（见第 9 节），没有配置文件就自动判断 |
| `--format {text,json,line}` | 输出格式，默认 `text`。`line` 是每条结果一行、修改建议接在 ` -- ` 后面，给编辑器和 grep 用 |
| `--strict` | 有 warning 也返回退出码 1 |
| `--info` | 显示 info 级别的结果（默认隐藏，只在汇总里计数） |
| `--no-color` | 关闭颜色。输出重定向到文件时会自动关闭 |
| `--watch` | 持续运行，文件一保存就重新检查，Ctrl+C 退出。VS Code 集成用的就是它（见第 7 节） |
| `--fix` | 自动修复能确定改法的问题，直接改写文件，再报告剩下的问题（见第 8 节） |
| `--diff` | 只把自动修复的内容以 diff 形式打印出来，不改文件 |
| `--config 文件` | 使用指定的配置文件，不再向上查找 `.nav2lint.yaml` |
| `--no-config` | 忽略所有 `.nav2lint.yaml` |
| `--version` | 显示版本号 |
| `--explain 规则` | 解释检查依据、处理建议和自动修复边界，不需要输入文件 |
| `--describe 参数 --distro 发行版` | 查询参数类型、来源与已知局限，必须明确指定发行版 |
| `--init-vscode [工作区]` | 创建或安全合并 VS Code 任务；省略工作区时使用当前目录 |
| `--python 可执行文件` | 指定初始化任务使用的 Python 命令，只能与 `--init-vscode` 一起使用 |

一次可以检查多个文件，也可以直接给一个目录：

```bash
nav2lint --distro humble config/*.yaml
nav2lint --distro humble ~/ros2_ws/src
```

给目录时，工具只挑出含有 Nav2 节点 `ros__parameters` 段落的 YAML。地图的 `map.yaml`、slam_toolbox 的配置这类文件会自动跳过，隐藏目录和 colcon 的 `build/`、`install/`、`log/` 也不会进去。直接写出文件名的文件则一定会被检查。

### 3.1 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 没有 error（加了 `--strict` 时：既没有 error 也没有 warning） |
| 1 | 有 error（加了 `--strict` 时：有 error 或 warning） |
| 2 | 文件读不了（路径不存在、没有权限等），或者配置文件写错了 |

### 3.2 JSON 输出

`--format json` 输出一个数组，每个文件一项：

```json
[
  {
    "path": "nav2_params.yaml",
    "distro": "humble",
    "distro_reason": "",
    "suppressed": 0,
    "findings": [
      {
        "rule": "E102",
        "severity": "error",
        "line": 26,
        "message": "`inflation_layer.inflation_radius` should be float but is int; ...",
        "hint": "write 1.0",
        "fixable": true
      }
    ]
  }
]
```

`distro_reason` 是自动判断发行版的依据。用 `--distro` 或配置文件指定时为空字符串；自动判断失败时 `distro` 为 `null`。`suppressed` 是被屏蔽的结果条数，`fixable` 表示这一条能用 `--fix` 自动修复。

---

## 4. 发行版判断

Humble、Jazzy、Kilted 的参数写法有区别，所以同一份文件放在不同版本上，检查结果不同。发行版按下面的顺序确定：命令行的 `--distro` 优先，其次是配置文件里的 `distro`，两者都没有时才自动判断。

- **指定发行版**：按指定版本检查，包括迁移规则（D2xx）。
- **自动判断（默认）**：工具会找只在某些版本出现的写法，并在第一行告诉你依据，例如：

  ```
  nav2_params.yaml: checking as humble (detected from: progress_checker_plugin)
  ```

  判断依据包括 `nav2_behaviors/Spin` 这类 `/` 分隔的插件名（Humble）、`progress_checker_plugins`（Jazzy 起）、`error_code_name_prefixes`（Kilted 起）等。

- **判断不出来**：文件里没有能区分版本的写法，或者新旧写法混在一起时，工具会跳过 D2xx 规则并提示：

  ```
  could not detect the distro (...); skipping migration checks, use --distro to set it
  ```

自动判断可能会错。比如一份 Jazzy 配置里已经写了 Kilted 才有的参数，就会被判成 Kilted，这个参数的问题也就查不出来了。所以**知道版本时请一定指定**：在工作区根目录放一个写着 `distro: humble` 的 `.nav2lint.yaml` 最省事（见第 9 节）。

### 迁移预检

想把 Humble 配置升级到 Jazzy，可以先用目标版本检查一遍旧文件：

```bash
nav2lint --distro jazzy humble_params.yaml
```

报出来的 D2xx 项就是需要改的地方，其中大部分可以自动改（见第 8 节）：

```bash
nav2lint --distro jazzy --diff humble_params.yaml   # 先看会改什么
nav2lint --distro jazzy --fix humble_params.yaml    # 确认后再改
```

---

## 5. 结果级别

| 级别 | 含义 | 建议 |
|---|---|---|
| **error** | 几乎肯定会出错：Nav2 启动报错、节点配置失败，或者这段参数完全不生效 | 必须改 |
| **warning** | 很可能是写错了，或者会让导航表现变差，但也可能是有意为之 | 逐条确认 |
| **info** | 提醒性质，通常没问题 | 了解一下即可，用 `--info` 才显示 |

---

## 6. 规则详解

规则编号的首字母代表类别：

- **N**：文件结构
- **E**：参数类型
- **P**：插件列表
- **D**：版本迁移
- **S**：参数之间是否合理
- **T**：拼写

### N：文件结构

**N001 YAML 语法错误（error）**
缩进错、括号没闭合等。这时文件无法解析，后面的规则都不会运行，先把语法修好。

文件不是 UTF-8 编码时也报 N001，并给出第一个非法字节所在的行。常见情况是用老编辑器存成了 GBK（ANSI）编码、里面又有中文注释，ROS 2 的 YAML 解析器同样会拒绝这种文件。用 VS Code 打开，在右下角把编码改成 UTF-8 后重新保存即可。`--fix` 不会改动这类文件。

**N002 重复 key（warning）**
同一层里同一个 key 出现两次。YAML 解析器只保留后一个值，不会报错。

```yaml
FollowPath:
  plugin: "nav2_rotation_shim_controller::RotationShimController"
  angular_dist_threshold: 0.785
  plugin: "dwb_core::DWBLocalPlanner"   # N002：覆盖了上面的 RotationShim
```

如果本意是用 RotationShim 包一层 DWB，应该写成 `primary_controller: "dwb_core::DWBLocalPlanner"`。

**N003 缺少 `ros__parameters`（error）**
ROS 2 只读取 `节点名: ros__parameters:` 下面的参数，最常见的写法错误是下划线只写了一个。

```yaml
amcl:
  ros_parameters:      # 错：应为 ros__parameters（两个下划线）
    alpha1: 0.2
```

**N004 costmap 只嵌套了一层（error）**
costmap 节点的全名是 `/local_costmap/local_costmap`，所以要嵌套两层：

```yaml
local_costmap:
  local_costmap:
    ros__parameters:
      resolution: 0.05
```

**N005 屏蔽注释里写了不存在的规则编号（warning）**
例如 `# nav2lint: disable=S399`。写错编号的屏蔽不会生效，所以单独提醒（见第 9 节）。

**N006 参数没有缩进到 `ros__parameters` 下面（error）**
参数和 `ros__parameters` 写在了同一层，YAML 语法上没错，但它们不属于 `ros__parameters`，ROS 2 不会把它们当作这个节点的参数。

```yaml
amcl:
  ros__parameters:
  alpha1: 0.2          # N006：和 ros__parameters 在同一层，要再缩进两格
  max_particles: 2000  # N006：同上
```

如果 `ros__parameters:` 下面什么都没有，报 warning（参数段是空的）。

### E：参数类型

**E101 数组类型不统一，或嵌套数组（error）**
ROS 2 的数组参数里所有元素必须是同一种类型，而且不支持嵌套数组。

```yaml
max_velocity: [0.5, 0, 2.0]            # 错：0 是整数，要写成 0.0
footprint: [[0.2, 0.2], [0.2, -0.2]]   # 错：嵌套数组
footprint: "[[0.2, 0.2], [0.2, -0.2], [-0.2, -0.2], [-0.2, 0.2]]"   # 对：Nav2 的 footprint 是字符串
```

**E102 类型与 Nav2 声明的类型不符（error）**
ROS 2 参数是强类型的。声明为 double 的参数写成整数，启动时会报 `parameter type mismatch`，这是 Nav2 最常见的启动错误。

```yaml
inflation_radius: 1      # 错
inflation_radius: 1.0    # 对
```

反过来也一样：整数参数（如 `max_particles`）写成 `2000.0` 也会报错。

参数类型来自 Nav2 源码里的声明（见第 11 节），覆盖所有官方节点和内置插件，包括官方配置里没写的参数，比如 RPP 的 `desired_linear_vel`。

### P：插件列表

Nav2 用列表参数来启用插件，例如 `plugins`、`controller_plugins`、`planner_plugins`、`behavior_plugins`、`goal_checker_plugins`。列表里的每个名字都对应下面一个同名的段落。

**P101 列表里有名字，但下面没有对应定义（error / warning）**

```yaml
controller_plugins: ["FollowPath", "Precise"]   # Precise 没有定义
```

`FollowPath`、`GridBased`、`static_layer` 这类 Nav2 默认 id 不会报，因为没写定义时 Nav2 会自动填默认插件。costmap 的 `observation_sources` 少定义时报 warning，collision_monitor 的 `polygons` 和 `observation_sources` 少定义时报 error。

**P102 插件段落缺少 `plugin` 字段（error）**

```yaml
goal_checker_plugins: ["my_checker"]
my_checker:
  xy_goal_tolerance: 0.25      # 缺 plugin: "nav2_controller::SimpleGoalChecker"
```

**P103 costmap 层定义了但没启用（info）**
写了 `inflation_layer:` 段落，但它不在 `plugins` 或 `filters` 列表里，所以不会被加载，改了参数也没有效果。Nav2 官方配置的 local_costmap 里就有一个没启用的 `static_layer`，这是正常的。

### D：版本迁移

这组规则只有在发行版确定时才会运行（见第 4 节）。

| 规则 | 级别 | 问题 | 改法 |
|---|---|---|---|
| D201 | error | Jazzy 起 Nav2 自带插件名用 `::`，`nav2_behaviors/Spin` 会加载失败 | 改为 `nav2_behaviors::Spin` |
| D201 | info | Jazzy 起第三方插件写成 `pkg/Class`；能否加载取决于该插件自己的 plugin XML 注册的名字（例如 STVL 注册的就是 `/` 形式） | 对照插件的 XML，确认后再改；不会自动修复 |
| D201 | warning | Humble 里 navfn、behaviors、smac、theta_star 的插件用 `/` 注册 | 改为 `nav2_navfn_planner/NavfnPlanner` 这种写法 |
| D202 | warning | Humble 用 `progress_checker_plugin`（字符串），Jazzy 起用 `progress_checker_plugins`（列表） | 按目标版本改 |
| D203 | warning | Jazzy 起 behavior_server 的 `costmap_topic` 改为 `local_costmap_topic`，`footprint_topic` 改为 `local_footprint_topic` | 按目标版本改 |
| D204 | warning | Jazzy 起内置 BT 节点会自动加载，`plugin_lib_names` 里列内置节点通常会导致重复注册报错 | 只保留自定义节点，或删掉整个参数 |
| D205 | error | Kilted 起 `error_code_names` 会让 bt_navigator 启动时抛异常 | 换成 `error_code_name_prefixes` |
| D205 | warning | Kilted 之前的版本不认识 `error_code_name_prefixes` | 换成 `error_code_names` |
| D206 | warning | Kilted 起 docking_server 的 `dock_backwards` 移到了 dock 插件里 | 在插件里写 `dock_direction: "backward"` |
| D207 | warning | Jazzy 起 Smac Hybrid 的 `viz_expansions` 改名 | 改为 `debug_visualizations` |
| D208 | warning | Jazzy 起 RPP 的 `use_interpolation` 已弃用 | 删掉 |
| D209 | warning | Jazzy 起 behavior_server 分 `local_frame` 和 `global_frame`；Humble 写的 `global_frame: odom` 在 Jazzy 里含义变了 | `local_frame: odom`，`global_frame: map` |
| D210 | error | collision_monitor 多边形 `points` 的格式：Humble 是扁平数组，Jazzy 起是字符串 | Humble：`[0.3, 0.3, 0.3, -0.3, ...]`；Jazzy：`"[[0.3, 0.3], [0.3, -0.3], ...]"` |
| D211 | warning | Humble 起 `recoveries_server` 改名为 `behavior_server`，旧名字下的参数没有节点会读取 | 改名，插件也换成 `nav2_behaviors` |

### S：参数之间是否合理

**S301 各节点 `use_sim_time` 不一致（warning）**
仿真时，如果有的节点用仿真时钟、有的用系统时钟，TF 时间戳会对不上，导致报 `extrapolation into the future` 之类的错误。工具会标出少数派的那几个节点。如果 launch 文件统一传入了 `use_sim_time`，这条可以忽略。

**S302 膨胀半径小于机器人半径（warning）**
机器人半径取 `robot_radius`，或由 `footprint` 算出外接圆半径。`inflation_radius` 比它还小时，规划出的路径会贴着障碍物走。

**S303 `raytrace_max_range` 小于 `obstacle_max_range`（warning）**
障碍物能在 3 m 处标记，却只在 2 m 内清除，那么 2–3 m 之间标记过的障碍物就清不掉，代价地图上会残留“鬼影”。

**S304 velocity_smoother 参数错误（error）**
以下情况 Nav2 会在配置阶段抛异常：
- `max_velocity`、`min_velocity`、`max_accel`、`max_decel` 不是 3 个元素 `[x, y, theta]`；
- `max_accel` 有负数；
- `max_decel` 有正数（减速度要写成负数）；
- `min_velocity` 某个分量大于 `max_velocity`。

**S305 控制器速度超过平滑器上限（warning）**
控制器输出的速度会被 velocity_smoother 截断，所以控制器里调高 `max_vel_x` 等速度参数不会生效。工具支持 DWB（`max_vel_x`、`max_vel_theta`）、MPPI（`vx_max`、`wz_max`）、RPP（`desired_linear_vel`）、Graceful（`v_linear_max`、`v_angular_max`）。

**S306 MPPI 参数不匹配（warning）**
- `model_dt` 不等于 `1 / controller_frequency`，Nav2 官方文档建议两者相等；
- 预测距离 `time_steps × model_dt × vx_max` 超过局部代价地图宽或高的一半，轨迹末端会落在地图外面，看不到那里的障碍物。

**S307 AMCL 粒子数上下限颠倒（warning）**
`min_particles` 大于 `max_particles`。

### T：拼写

**T401 节点名拼错**，例如 `controler_server`，会提示“是不是 `controller_server`？”。节点名拼错后，这整段参数都不会被读取。

**T402 插件名拼错**，例如 `nav2_costmap_2d::InflationLyer`。

**T403 参数名拼错（第三方插件）**：Nav2 参数表里没有的节点或插件（比如第三方控制器），只能靠拼写判断。只有参数名里出现了**不认识的单词**时才会报，比如 `inflation_raduis`；`min_vel_theta` 这种每个词都认识的不会报。

**T404 参数未被当前参数表收录（warning）**：对已知节点和内置插件，工具结合源码提取表与官方参考配置检查参数。参数表并不保证完整，**未收录不等于 Nav2 一定不会读取**。应核对发行版、插件类型和源码。常见原因：
- 拼错了，提示里会给出最接近的参数名；
- 参数属于别的版本，提示里会写 “exists in kilted, rolling” 这样的说明；
- 参数写在了错误的插件下面。例如 linorobot2 的配置里，RotationShim 的参数因为 `plugin` 重复被留在了 DWB 下面，这些参数会被逐条报出来。

```yaml
bt_navigator:
  ros__parameters:
    enable_groot_monitoring: true   # T404（humble）：Humble 已经没有这个参数
```

---

## 7. 在 VS Code 里显示

不需要专用扩展。v0.3.0 可以直接生成任务，不再要求手改固定的 D 盘路径：

```bash
cd ~/ros2_ws
nav2lint --init-vscode .
```

如果所用的 WSL Python 已安装 nav2lint，也可以明确指定解释器：

```bash
python3 -m nav2lint --init-vscode . --python python3
```

默认使用运行 nav2lint 的当前 Python；指定 `--python` 时，用户需确保该命令能导入 nav2lint。工具不会执行指定命令，也不会替它安装依赖。通过 `PYTHONPATH` 临时运行源码的用户，建议先在任务使用的环境中 `pip install -e /path/to/nav2lint`，因为任务不会自动继承此次临时设置的 `PYTHONPATH`。

初始化仅补入缺少的任务，不覆盖已有同名任务，不自动运行任务，也不自动启用打开文件夹时执行。支持带注释和尾随逗号的 JSONC，合并保留已有文本、注释和换行。遇到坏格式、重复 JSON key 等不能安全处理的情况，会报错且保留原文件。已有旧版任务（包括固定路径和自动启动设置）会保留；如需换成新版，先备份后移除旧的两个 nav2lint 任务，再初始化。

两个任务均从命令面板的 “Tasks: Run Task” 手动启动：

- **nav2lint: watch workspace**：运行期间持续检查工作区，保存参数文件后重新检查。
- **nav2lint: check current file**：检查当前文件一次。

problem matcher 将诊断送入 VS Code 的“问题”面板。发行版仍写在工作区根目录的 `.nav2lint.yaml` 中，例如 `distro: humble`。本轮验证覆盖任务内容、输出匹配和初始化行为，未人工观察编辑器波浪线界面。

Windows VS Code 窗口应使用 Windows Python；Remote-WSL 窗口应在 WSL 中初始化并使用 WSL Python。默认生成的解释器绝对路径适用于当前环境；换机器后可重新初始化，或明确选择各机器 PATH 上可用的 Python 命令。进程任务不会自动采用 Python 扩展选中的解释器。

[editors/vscode/tasks.json](../editors/vscode/tasks.json) 仍可作为手动复制的通用模板，使用前确认其中的 Python 命令正确。

### 7.1 任务列表为空时

- 打开的是包含 `.vscode/tasks.json` 的工作区根文件夹，而不是单个 YAML 或下级目录；任务名不是独立的命令面板命令，要先选择“任务: 运行任务”，必要时点“显示所有任务”。
- 确认工作区信任状态。配置从外部修改后，可先保存工作，再执行 “Developer: Reload Window”。
- Windows VS Code 通过 WSL UNC 共享路径打开目录时，本机曾出现文件监听错误；日志只能证明监听异常，不能认定所有任务缺失都由它造成。可用 Remote-WSL，或创建保存在 Windows 本地的 `.code-workspace` 文件，在其中放入 WSL 文件夹 URI 及工作区级 `tasks`，再打开该工作区。
- 本机实际验证可见任务的入口是 `D:\projects\nav2lint_data\ros2-nav2lint.code-workspace`。它是个人环境配置，不随开源仓库发布，也不修改导航参数。
- `/path/to/...` 是通用示例的占位符，必须替换为实际路径；不应复制它去创建根目录，也不需要用 sudo 绕过权限。Ubuntu 默认命令通常是 `python3`，不是 `python`。

## 8. 自动修复（--fix）

有一部分问题，正确写法只有一种，工具可以直接替你改：

```bash
nav2lint --diff nav2_params.yaml   # 先看会改什么，不动文件
nav2lint --fix nav2_params.yaml    # 改写文件，然后报告剩下的问题
```

`--fix` 只改有问题的那几行，注释、顺序、缩进和 Windows 的 CRLF 换行都保持原样。汇总行里会写 “N fixable with --fix”，告诉你有几条能自动修复。

| 规则 | `--fix` 做的修改 |
|---|---|
| N003 | `ros_parameters` 改成 `ros__parameters` |
| E101 | 行内数组里的整数改成浮点数；写成行内嵌套列表的 `footprint` 加上引号变成字符串 |
| E102 | double 参数的 `1` 改成 `1.0`，整数参数的 `2000.0` 改成 `2000`，行内整数数组改成浮点数组 |
| D201 | 按目标版本把 Nav2 自带插件名的 `/` 和 `::` 互换（第三方插件不改） |
| D202 | `progress_checker_plugin: "x"` 和 `progress_checker_plugins: ["x"]` 互换 |
| D203 | behavior_server 话题参数改名 |
| D204 | 从 `plugin_lib_names` 里删掉内置 BT 节点；删完为空时把这个参数也删掉 |
| D207 | `viz_expansions` 改成 `debug_visualizations` |
| D209 | `global_frame: odom` 改成 `local_frame: odom` 加 `global_frame: map` 两行 |
| D210 | collision_monitor 多边形 `points` 在扁平数组和字符串两种写法之间转换 |
| S304 | 修正 `max_accel` / `max_decel` 的正负号 |

不会自动修复的：
- 拼写类（T401–T404）：“是不是 X” 只是猜测，可能猜错，需要你自己判断。
- 需要理解意图的问题，比如重复 key、`use_sim_time` 不一致、参数之间的大小关系。
- 写成多行（block 风格）的数组，只有写在一行里的 `[...]` 才会改。
- 被屏蔽注释或配置文件关掉的规则。

我用 Nav2 官方的 Humble 配置试过：`--fix --distro jazzy` 一次改了 11 处，改完按 Jazzy 检查是 0 error、0 warning。

## 9. 配置文件与屏蔽注释

### 9.1 配置文件 `.nav2lint.yaml`

放在工作区根目录（或任意上级目录）。检查一个文件时，工具从这个文件所在目录开始往上找，用找到的第一个配置文件：

```yaml
distro: humble          # 不写 --distro 时用这个发行版
disable: [S301]         # 关掉这些规则
severity:               # 修改规则的级别：error / warning / info
  T404: info
```

三个字段都可以省略。字段名、发行版或规则编号写错时，工具会报 `config error` 并以退出码 2 结束，不会悄悄忽略。`--config 文件` 用于指定配置文件，`--no-config` 用于忽略配置文件。

### 9.2 屏蔽注释

只想屏蔽某一条结果时，在参数文件里加注释：

```yaml
use_sim_time: False  # nav2lint: disable=S301   这一行
# nav2lint: disable-next-line=T404               下一行
# nav2lint: disable-file=S305                    整个文件
# nav2lint: disable                              不写编号：这一行的所有规则
```

- 多个编号用逗号分隔：`disable=S301,T404`。
- 编号后面可以写理由，工具会忽略：`# nav2lint: disable=S301 launch 文件统一设置了 use_sim_time`。
- 结果的行号就是报告里显示的那一行，屏蔽注释要写在那一行（或用 `disable-next-line` 写在它上面一行）。
- 被屏蔽的条数会显示在汇总行里（如 “1 suppressed”），不会完全看不见。

## 10. 在 Python 里调用

```python
from nav2lint import fix_text, lint_file, lint_text

res = lint_file("nav2_params.yaml", distro="humble")
print(res.distro, res.errors, res.fixable)
for f in res.findings:
    print(f.line, f.severity, f.rule, f.message, f.hint)

new_text, n_fixed, remaining = fix_text(open("nav2_params.yaml", encoding="utf-8").read(), distro="jazzy")
```

`lint_text(text, distro=None, path="<string>", config=None)` 直接检查字符串，适合在 launch 文件或测试里调用。`distro=None` 时使用配置里的发行版，没有配置就自动判断。

---

## 11. 工作原理与局限

**原理**
- 参数名和类型有两个来源：
  - 从 Nav2 各发行版源码中提取的参数表（`src/nav2lint/data/`，由 `tools/extract_params.py` 生成，记录了对应的 navigation2 commit）。提取器识别 `declare_parameter`、`declare_parameter_if_not_declared`、costmap 的 `declareParameter`、MPPI 的 `getParam`、DWB 的 `searchAndGetParam`、`declare_or_get_parameter`，以及 Python 节点（Jazzy/Kilted 的 loopback simulator）里的 `self.declare_parameter`，类型取自默认值。每个版本 1000–1700 个参数；
  - 各发行版官方的 `nav2_bringup/params/nav2_params.yaml`（`src/nav2lint/refs/`），用来补上提取器漏掉的少数参数。
- 迁移规则来自 Nav2 官方迁移指南，并对照 navigation2 各分支的源码核对过。
- 读 YAML 时保留每个值的行号，并检查重复 key。普通 YAML 库做不到这两点。
- 科学计数法 `1e-10` 按 ROS 2 的规则当作浮点数（普通 YAML 1.1 解析器会把它当成字符串）。

**局限**
- 第三方插件和节点不在参数表里，只做结构检查和保守的拼写检查（T403）。
- 参数表是对 C++ 代码的静态读取。用特殊方式声明的参数可能会漏掉，表现为 T404 误报。
- 不解析 launch 文件。launch 里用 `RewrittenYaml` 或命令行覆盖的参数，工具看不到。
- 不检查行为树 XML。
- 工具只读参数文件，不能代替实际运行。没有报错不代表导航一定正常。

---

## 12. 规则解释与参数来源查询（v0.3.0）

```bash
nav2lint --explain T404
nav2lint --describe controller_server.controller_frequency --distro humble
nav2lint --describe plugin:nav2_costmap_2d::InflationLayer.inflation_radius --distro jazzy
nav2lint --describe plugin:dwb_core::DWBLocalPlanner/PathAlign.scale --distro humble
nav2lint --describe amcl.initial_pose.x --distro humble --format json
```

这些命令不需要参数文件。查询只支持 text 和 json，不与文件检查、修复或 watch 模式组合。

- `--explain` 说明规则检查什么、应如何处理、哪些情况可以自动修复。
- `--describe` 必须明确指定发行版，不从当前目录的配置自动读取。插件使用 `plugin:包名::类名/分组.参数`，不能仅凭实例名 `FollowPath` 推断插件类型。
- `source_table` 表示源码提取表，包含 Nav2 commit 和数据文件路径；`source_table_global` 表示继承的全局声明；`reference_yaml` 表示官方参考配置；`built_in_convention` 表示内建 rclcpp 参数约定。
- `known` 表示有记录，不保证类型已知；`not_in_tables` 表示该作用域有表但没找到参数；`unknown_scope` 表示作用域没有表。`type_known` 单独说明是否知道类型，`scope_complete` 当前均为 false。
- 已提取的数据未记录逐参数 C++ 文件和行号，不能据此跳转到具体声明行。
- 查询成功返回 0，即使参数未收录；规则 ID、语法或发行版错误返回 2。

JSON 诊断为 E102 和 T404 增加 `evidence` 列表，给出参数的已知类型和来源；其他规则目前列表为空，可用 `--explain` 查规则解释。它不提供未经校准的“置信度百分比”。

## 13. pre-commit 与自动测试

其他仓库可配置：

```yaml
repos:
  - repo: https://github.com/Leonhart999/nav2lint
    rev: v0.3.1
    hooks:
      - id: nav2lint
```

hook 不自动修复；相关 YAML 改动触发后扫描整个工作树中的 Nav2 参数文件，而不是把地图等所有 YAML 都当作参数文件。它可能报告尚未暂存的修改或已有问题。发行版在 `.nav2lint.yaml` 设置，想让 warning 也阻止提交，可添加 `args: [., --strict]`。

仓库新增 Windows/Linux 多 Python 版本的 CI、wheel 安装验证和提取器小型回归样例。CI 文件存在不代表已经在 GitHub 跑过，发布时应以实际 Actions 结果为准。

## 14. 常见问题

**Q：为什么官方配置也报了一条 info？**
官方 local_costmap 里定义了 `static_layer`，但它没在 `plugins` 列表里（局部代价地图通常不需要静态层）。这条 P103 是事实描述，不需要改。

**Q：我的参数明明是对的，却报了 E102 或 T404？**
先确认 `--distro` 和你实际用的版本一致：同一个参数在不同版本里可能不存在，或者类型不同。T404 的提示里会写这个参数存在于哪些版本。如果版本没错，可能是提取器漏掉了这个参数，记下参数名，以后可以修正提取器。

**Q：没有报任何问题，但 Nav2 还是启动失败？**
看第 11 节的局限：launch 文件覆盖的参数、BT XML、第三方插件的参数类型，这个工具都不检查。这种情况要看 `ros2 launch` 的日志。

**Q：WSL 里提示 `command not found`？**
alias 没生效。执行 `source ~/.bashrc`，或者直接用 `PYTHONPATH=/mnt/d/projects/nav2lint/src python3 -m nav2lint ...`。
