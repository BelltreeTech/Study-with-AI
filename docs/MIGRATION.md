# データ保護・移行・復旧

## 今回実施したことと実施していないこと

本人の既存 `user_data/progress.json` は作業開始時に担当エージェントが Git 管理外へバックアップした。追跡解除では作業ツリー上の元ファイルを保持し、履歴は書き換えていない。ファイルの内容をテスト fixture、ログ、文書へ転載しない。

移行、並行保存、XP の冪等性、rollback のテストは一時ディレクトリ内の合成データだけで行った。合成テスト成功後、2026-09-19に既存 `progress.json` の **本移行** を `scripts/migrate_progress.py` で実施した。本人の実進捗をアプリ起動・学習・採点のテストに使用していない。

本移行は、直前の非公開バックアップと元JSONのバイト一致、移行後の全値と期待される変換結果の一致、元JSONが変更されていないことを確認した。コース名・点数・本文は出力していない。移行結果は `user_data/progress.sqlite3`、schema version 1。元JSONを含むGit外の開始時backupに加え、移行時のJSON・SQLite snapshot・private manifestを保持している。具体的なローカル保存先は作業の完了報告に記録し、個人のパスや内容を共有文書へ追加しない。

別の保存領域では、初回起動時に下記の一度だけの移行が行われる。バックアップも明示的に作る場合は、アプリを停止し、保存先とGit外のバックアップ先を指定する。

```sh
uv run --frozen python scripts/migrate_progress.py \
  --state-dir user_data --backup-root "$HOME/Study-with-AI-backups"
```

再実行時は既存SQLiteを初期化し直さず、旧JSONの変更による上書きもしない。再実行・破損・未知フィールド・rollbackは合成データで検証している。

## 保存先と形式

- `STUDY_STATE_DIR` の既定はリポジトリ直下の `user_data/`。
- 進捗は `progress.sqlite3`。`repository_meta.schema_version=1` で形式を管理する。
- 旧 `progress.json` は読み取り専用の移行元として保持する。
- ジョブ DB は JobManager に渡す保存先に作成され、`jobs_meta.schema_version=1` を持つ。学習履歴の DB は UI/Service の設定に従う。
- SQLite は WAL と同期書込みを使用する。保存先 DB は作成時から所有者だけが読み書きできる `0600`。DB/WAL/SHM、lock、教材、モデル、cache、ログを Git へ追加しない。
- ジョブ DB には要求入力と検証済み結果が含まれるため、本人の学習データとして扱う。診断の `list_jobs()` は状態と日時等のメタデータだけを返す。

## 進捗の一度だけの移行

1. SQLite の初期化ロックを取得し、`BEGIN IMMEDIATE` の中で現在のスキーマ版と保存済み state を確認する。
2. state が未作成で旧 JSON が存在する場合だけ全文を検証する。JSON/既存 SQLite が破損している場合は例外として停止し、空データに置き換えない。
3. 複数コース形式は不明なトップレベル・コース・プロフィールフィールドを含めて保持する。「集中学習」というコースも名前だけで削除しない。
4. 単一コース旧形式は `topic` のコースへ移し、旧フィールドも保全する。空 topic の名称だけ `Default Course` とする。
5. 移行元の JSON 原文、SHA-256、移行日時を `migration_sources` に保存する。元 JSON ファイル自体は一切書き換えない。
6. state と移行記録を同じ transaction で commit する。以降の起動は SQLite を使用し、移行元 JSON の変更による上書きや二重加算を行わない。

コース更新では `curriculum` と `current_chapter_index` を更新し、弱点・XP・成績・未知フィールドを消さない。各更新は同じ transaction 内で最新 state を読み直すため、別タブ・別プロセスの更新による read-modify-write の取りこぼしを防ぐ。

## 学習完了・XP・復習

`commit_learning_event(course_name, event_id, ...)` は採点・弱点・章完了・XP・ポモドーロを一つの transaction で保存する。Service は検証済み `succeeded` ジョブだけをこの関数へ渡す。同じ job/attempt を画面 rerun で再処理しても、`progress_events` の一意なイベント ID により二重加算されない。同じ ID に異なる結果を渡す場合はエラーとなる。意図的な再受験・再生成は新しい attempt/request ID を使う。

互換関数 `add_exp` 等は `event_id` を省略できるが、その場合は呼出しごとに独立したイベントと見なす。新しい UI/Service は stable なイベント ID、またはまとめて保存する `commit_learning_event` を使う。

日時は Asia/Tokyo。復習予定は日本日付、履歴の日時は `+09:00` 付き ISO 8601。日付が変わったときの表示用 daily XP は 0 とし、前日の daily XP で当日のストリークを達成させない。

## ジョブ中断と再開

ジョブは queued / running / succeeded / failed / cancelled / interrupted を区別する。SQLite の状態と OS の排他 lock で、同じジョブ DB を共有するアプリの生成同時実行数を 1 にする。CLI 子プロセスにも実行 lock の descriptor を継承し、親が異常終了しても、残った子が終了する前に新しい生成を開始させない。

再起動後、実行 lock の解放が確認できた running ジョブ、および所有プロセスが終了済みの queued ジョブは interrupted にする。結果として成功扱いせず、利用枠を消費する自動再実行もしない。キャンセル後に worker が結果を返しても破棄する。正常終了では自身のジョブにキャンセルを通知し、Provider による子プロセス回収を待つ。他の Codex セッションを kill しない。

この実装は macOS/Linux の `fcntl.flock` を使う。Windows は未対応・未検証。別々の `STUDY_STATE_DIR` を意図的に指定したインスタンスは異なるアプリ保存領域なので、互いに同時実行数を共有しない。queued ジョブの孤立検出は OS プロセス ID の生存確認を用いるため、異常終了後にその PID が再利用される稀な場合は pending が自動復旧しない可能性がある。その場合も勝手に再実行はされない。

## バックアップ

旧 JSON と設定済み保存領域のバックアップを Git の外に置く。教材全体の複製は必要な場合に限る。

稼働中の `progress.sqlite3` を単にコピーすると WAL 内の最新変更を含まない場合がある。アプリを正常停止してから保存領域一式をバックアップするか、SQLite online backup API を利用する。以下は新しい一意な保存先を明示した場合の例で、既存ファイルは上書きしない。

```python
from pathlib import Path
from src.progress import get_repository

# 実行すると設定済み保存領域を開く。実データでの試験には使用しない。
backup = Path.home() / "Study-with-AI-backups" / "progress-YYYYMMDD-HHMMSS.sqlite3"
get_repository().backup(backup)
```

ジョブや学習履歴の DB も必要な場合は、アプリ停止後に DB/WAL/SHM を同じ時点の組として保管する。`.tmp` や他プロジェクトのファイルを一括削除しない。

## rollback

1. アプリを正常停止し、自身の Codex ジョブの終了を待つ。
2. 現在の保存領域を新しい名前で Git 外へバックアップする。SQLite、元 JSON、関連 WAL/SHM を保持する。
3. 改修前のコードを利用する場合は、別の明示した復旧ディレクトリに保管済みの旧 `progress.json` を置く。今回の移行は元 JSON を変えていないため、移行直前の状態をそのまま復元できる。
4. 新コードで SQLite snapshot を復元する場合も、既存保存先を上書きせず、空の別ディレクトリへ snapshot を `progress.sqlite3` として配置し `STUDY_STATE_DIR` で指定する。同時点でない古い WAL/SHM を復元先へ混ぜない。
5. 合成テストと同様にコース件数・主要値を比較し、復元先での表示確認後に日常利用先を切り替える。

新コードを利用した後の SQLite 変更は、保持された旧 JSON には反映されない。旧コードへ戻すときに新しい学習分も必要なら、別途の逆移行が必要であり、現時点では自動逆移行を実装していない。元 JSON への無断上書きで解決しない。

## 検索インデックス

旧 API ベクトルを新しいローカル Embedding のベクトルと混合しない。旧 cache を破壊せず、Retriever の新 namespace に再構築する。教材を再配置・差し替えた場合は、内容ハッシュとページ・chunk metadata に基づき再構築する。ローカルモデル未取得時には BM25 検索を使い、意味検索が無効であることを表示する。

## 合成データでの検証

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_repository.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_jobs.py' -v
```

移行元原文/未知 fields 保全、単一コース旧形式、再移行防止、破損時停止、未来 schema 拒否、コース付随値保全、並行 XP 更新、一度だけの学習イベント、ポモドーロ、復習、日付、WAL を含む backup を検証する。ジョブ側は別プロセス並行実行、初期化 race、キャンセル後の結果破棄、終了時回収、再起動 orphan、親異常終了時の継承 lock、診断への本文漏れ防止を検証する。実行結果の確定件数と実行環境は `docs/TEST_REPORT.md` に記録する。
