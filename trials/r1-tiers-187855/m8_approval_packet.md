# M8 人工批准材料

本次重放的是作业 `187767` 的冻结标签与原始记录。M8 已重新生成 484 个审核单元，R2b 225 个，R2a 259 个。正式审核状态为 `PENDING_HUMAN_REVIEW`。既有抽查仍只作为 `provisional: true` 的干跑依据。

## 标签定义和例子

| 标签 | 用户审阅口径 | 实际例子 |
|---|---|---|
| R2b 完全重复搜索 | 以前搜过同样的词，当前又得到了同一份可见内容。 | `948__rep2:11`，搜索词 `"Leakey father wanted him to study medicine PhD 1960s"` |
| R2a 零新信息 | 换了搜索词，结果里的所有文档以前都见过。 | `1003__rep3:8`，搜索词 `"cited as research associate 2009 alcohol study author book 2008"` |
| R2a 重复取证 | 有文档首次出现，但当前返回的证据文档全都已经见过。 | `1085__rep2:2`，搜索词 `"Belford Clarke Co. 1880s author journalist book published"` |

## 代码怎么判

- 只与更早轮次的搜索比较。同轮并行调用共享轮前账本。可见返回按 docid 记账，问题级 evidence 快照区分证据文档和其他文档。
- R2b 要求相同的已认证检索环境、工具和有效参数。搜索词比较前做 NFKC、casefold、空白折叠。成功返回的 docid 集合一致或原返回内容哈希一致，并且先前匹配返回当前仍可见，才允许判阳性。
- R2a 要求可用的可见返回、R2b 未判阳性，且没有保护规则触发。先检查全部 docid 已见过，再检查本次的 evidence docid 全已见过。
- 首次找到证据或新证据、解决冲突、独立佐证、从摘要转查全文、恢复不可见证据、工具错误后的合理重试均受保护。不可用返回或解析失败会导致弃权。并行调用或缺少可验证的策略 token 位置也无法计价。

## 187333 抽查与全量计数

- 完全重复 10/10。`342__rep3:15`、`1188__rep3:19`、`132__rep1:17`、`282__rep3:11`、`618__rep1:18`、`233__rep4:15`、`405__rep2:17`、`231__rep1:16`、`1188__rep4:14`、`405__rep2:11`
- 零新信息与重复取证的无新收获抽查合计 40/40。以下两组沿用原抽样分组，每组 20 个。187333 的分组依据是搜索词意图，R2a 的两个子类依据是返回内容。
  - 高确定性非原样重复 20/20。`317__rep1:10`、`528__rep4:7`、`429__rep2:16`、`228__rep3:18`、`231__rep1:10`、`266__rep2:15`、`1085__rep4:6`、`266__rep3:6`、`270__rep4:14`、`233__rep3:11`、`392__rep4:8`、`1078__rep3:18`、`556__rep2:11`、`618__rep4:8`、`551__rep1:13`、`1003__rep2:8`、`624__rep2:8`、`23__rep3:13`、`773__rep3:8`、`527__rep3:14`
  - 软冗余 20/20。`410__rep4:6`、`410__rep3:5`、`410__rep1:6`、`1096__rep1:3`、`408__rep1:3`、`773__rep3:6`、`1247__rep1:10`、`408__rep4:6`、`301__rep2:15`、`228__rep2:16`、`55__rep2:10`、`410__rep4:4`、`410__rep4:16`、`527__rep3:17`、`226__rep2:14`、`410__rep4:7`、`202__rep1:4`、`853__rep1:8`、`556__rep4:9`、`410__rep1:3`

全量 R2b 阳性 229 次。R2a 阳性 1,409 次，其中零新信息 882 次、重复取证 527 次。

## 定价

R2b 基础价格为 0.10。187767 启用了成本加权，按事件成本与开发集基准的比值缩放，倍率最高为 2。R2a 的价格为 0，只记录；R1 也只记录。每条轨迹累计扣分上限为 0.5。每条轨迹只有在组内至少一条其他轨迹答对时才开启过程扣分；同组无人答对时扣分为 0。触发预算组保护时也会关闭该组的过程扣分。

## 用户怎么批准

1. 打开祝融私有目录 `/file_storage01/home/weiyu/lanyi/projects/redundancy-judge-phase1/r1-tiers-cf57838c43e2/run-187855/m8/` 下的 `human_review_template.csv` 和 `human_review_packets.jsonl`。按每条审核单元独立填写 `human_decision`（`positive`、`negative` 或 `abstain`）、`necessary`、`reviewer_id` 和适用的 `protection_reason`。保留模板的事件 ID、标签、抽样类型和抽样概率，设置 `source="human"`、`independent=true`；JSONL 中的布尔值使用 JSON 布尔类型。出现评审分歧时，由独立裁决者另填一条记录并设置 `adjudication=true`。
2. 把记录导出为 `human_annotations.jsonl`，把 `/file_storage01/home/weiyu/lanyi/projects/redundancy-judge-phase1/r1-tiers-cf57838c43e2/run-187855/m8_config.json` 中的 `human_annotations` 指向该文件的绝对路径。如有经人工核对、能映射到本次冻结事件的删除对照，设置 `reviewed_legacy_links` 指向其 JSONL。187333 的抽查只能保留为临时批准；若正式审核所需的统计区间或 B⁺ 对照证据不足，审核器会保留待审或证据不足状态。当前 R2a 从不定价，依赖可计价事件的指标也可能无法形成正式批准所需的区间。
3. 从登录节点提交审核。命令只读取起始冻结产物和人工记录，写入本次材料的私有 M8 目录。

   ```bash
   sbatch --partition=gre --account=professors --cpus-per-task=2 --mem=12G \
     --time=00:20:00 --output=/file_storage01/home/weiyu/lanyi/projects/redundancy-judge-phase1/r1-tiers-cf57838c43e2/run-187855/m8/signoff-%j.log \
     --wrap='PYTHONPATH=/file_storage01/home/weiyu/lanyi/projects/redundancy-judge-phase1/r1-tiers-cf57838c43e2/src PYTHONDONTWRITEBYTECODE=1 /file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python -m redundancy_judge.cli audit --config /file_storage01/home/weiyu/lanyi/projects/redundancy-judge-phase1/r1-tiers-cf57838c43e2/run-187855/m8_config.json'
   ```

4. 查阅 `/file_storage01/home/weiyu/lanyi/projects/redundancy-judge-phase1/r1-tiers-cf57838c43e2/run-187855/m8/acceptance.json`。通过的标签由程序写入同目录的 `approved_labels.json`，并绑定 187767 的冻结身份。批准只允许同一冻结身份下、满足保护和可计价检查的 R2b 进入已配置的过程扣分。R2a 与 R1 继续只记录。这条命令不会启动训练。

