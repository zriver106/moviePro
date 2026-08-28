# dreamina —— 即梦 CLI 的 skill

`SKILL.md` 是即梦官方安装脚本下发的，**从 `~/.dreamina_cli/dreamina/` 拷进项目根目录**，
不留在仓库外面 —— 外面那份会被下次 `curl | bash` 覆盖，而我们要的是一份
跟着这个仓库走、能进 git、能回溯的副本。

`.claude/skills/dreamina` 是指到这里的 symlink（一份源，不分叉）。

## 更新

即梦官方更新 SKILL 时，重跑安装脚本再拷一次：

```bash
curl -s https://jimeng.jianying.com/cli | bash
cp ~/.dreamina_cli/dreamina/SKILL.md dreamina/SKILL.md
git diff dreamina/SKILL.md      # 看它改了什么再决定要不要跟
```

**别直接 symlink 到 `~/.dreamina_cli`** —— 那样官方一更新，我们这边的行为
就会在没人察觉的情况下改变，而 git 里看不到任何改动。

## 边界

即梦跑的是 Seedance 2.5 / Image 2，跟我们主链路的 fal
（Seedream v5 lite + Seedance 2.0/2.5）是**两条独立通道、两套计费**。
要接进流水线得先想清楚是替代还是并存 —— 并存的话同一个资产会在两边各出一次，
那正是我们记过的「分开生成必漂」。
