# 时区策略：内部 aware UTC，对外 naive（保 Java 前端往返）

Java 用 `LocalDateTime` 存取，API 返回无时区后缀的本地时间串；R5 review 发现 Python 侧全部 ORM 列与迁移均为 naive `DateTime`，正确性隐式依赖"部署服务器时区须为 UTC"这一未强制假设，且已出现一处 `datetime.now(UTC)` 写入 naive 列的漂移。全新空库（ADR-0002）无存量数据迁移风险。

我们决定：**内部统一 aware UTC，边界对称（入口挂 UTC、出口剥偏移）**。

- **列**：全部 datetime 列改 `DateTime(timezone=True)`（Postgres timestamptz）；新增追加式 alembic 迁移 010 用 `ALTER COLUMN ... TYPE timestamptz USING <col> AT TIME ZONE 'UTC'` 把既有 naive 值按 UTC 解释（ADR-0002 版本化纪律，不改历史脚本）。
- **应用时钟**：禁止裸 `datetime.now()`/`datetime.utcnow()`，一律 `datetime.now(UTC)`。
- **DB 默认值**：保留 `func.now()`——timestamptz 下 `now()` 记录的是绝对时刻，与服务器 timezone GUC 无关，天然安全。
- **输入边界**：前端回传的无偏移本地 wall-clock 串（经 `datetime.fromisoformat`）挂 UTC（`.replace(tzinfo=UTC)`）。
- **输出边界**：响应 DTO 的 datetime 字段序列化时**剥掉偏移**，wire format 与今天逐字节一致。已核实复用的 React+TS 前端读（`new Date`/`dayjs` 按本地解析）与写（日历回传 `YYYY-MM-DDTHH:mm:ss` 无偏移）契约均为无偏移本地串；若对外发 `+00:00`/`Z`，前端会把时间当 UTC 再转本地，导致 interviewTime 往返偏移（填 14:00 回显 22:00）。
- **守卫**：新增 fitness 测试——扫 ORM 断言每个 DateTime 列带 `timezone=True`；扫应用代码禁止裸时钟调用。

**不变量**：前端发 `14:00:00` → 挂 UTC 存 `14:00+00:00` → 出口剥偏移回 `14:00:00` → 前端仍显示 14:00；调度器 `interview_time < now` 两侧皆 aware UTC，无 TypeError 且与现状语义一致。

**Considered Options**：
- 内部 aware / 对外**也**发偏移（emit `Z`）——**否**：破坏 interviewTime 前端往返，且需改前端（本次仅迁后端，ADR-0001）。
- 保持 naive、仅强制服务器 UTC（TZ=UTC）——**否**：保留"正确性依赖服务器时区"的脆弱性，正是本 ADR 要消除的。
- 输入按配置时区（如 Asia/Shanghai）转 UTC——**否**：系统无用户时区来源，徒增配置与往返复杂度。
