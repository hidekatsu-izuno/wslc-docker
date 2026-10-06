# wslc-docker

WSLのUbuntuから `docker` コマンドでWindowsの `wslc.exe` を呼ぶスクリプト群です。
Docker CLI変換処理と、PyYAMLを使うCompose実装を同梱しています。

**主要Docker CLI操作の互換ラッパーです。Docker Engine APIやDocker全機能の完全互換実装ではありません。**
出力のJSON項目・テーブル表示や各機能の挙動はwslcに依存します。

## 導入

Windows側でWSLコンテナー機能と `wslc.exe` が動作するUbuntu/WSL環境が必要です。Python 3とPyYAMLはdebの依存関係としてaptがインストールします。

[GitHub Actions](https://github.com/hidekatsu-izuno/wslc-docker/actions) の成功したビルドから **Artifacts** のZIPをダウンロードし、展開したdebをUbuntu内でインストールします。

```bash
sudo apt install ./wslc-docker_*.deb
docker run --rm hello-world
docker compose -f compose.yaml up -d
```

インストールすると `/usr/bin/docker` と `/usr/bin/docker-compose` がwslc向けラッパーになります。PATHの変更、手動でのシンボリックリンク作成は不要です。`docker-wslc`、`wslc-docker`、`wslc-compose` も `/usr/bin` に登録されます。

既存のDocker CLIを持つ `docker.io`、`docker-cli`、`docker-ce-cli`、`podman-docker`、`moby-cli`、`docker-compose` とはパッケージの `Conflicts` で競合を宣言しています。該当パッケージが入っている場合、aptはそのパッケージと依存するパッケージの削除を提案します。aptが表示する削除対象を確認してインストールしてください。

通常はPATH上の `wslc.exe` または `/mnt/c/Program Files/WSL/wslc.exe` を自動検出します。カスタム配置の場合は `WSLC_DOCKER_BIN` と `WSLC_COMPOSE_BIN` を指定してください。

以前の手順で `alias docker=...` や `~/.local/bin/docker` を作成した場合、その設定が `/usr/bin/docker` より優先されることがあります。debへ切り替える際に以前の設定を一度削除してください。以前 `install.sh` を使って導入した場合は、そのソースディレクトリーで `bash uninstall.sh` を実行してからdebをインストールしてください。

## 使用例

```bash
docker pull alpine:3.22
docker run --rm -it alpine:3.22 sh
docker run -d --name web -p 8080:80 nginx:alpine
docker ps -a
docker logs -f web
docker exec -it web sh
docker stop web
docker rm web

# ローカルのビルドコンテキストとDockerfile
docker build -t sample:local -f examples/Dockerfile examples
docker run --rm sample:local

# ホスト側のパスだけを変換。/workはコンテナー内のパスのまま。
docker run --rm -v "$PWD:/work:ro" -w /work alpine:3.22 ls -la
docker run --rm --mount "type=bind,source=$PWD,target=/work,readonly" alpine:3.22 ls /work

# Ubuntu側の環境変数を受け渡す
export APP_MODE=development
docker run --rm -e APP_MODE alpine:3.22 printenv APP_MODE
docker run --rm --env-file ./app.env alpine:3.22 env

# コピー、アーカイブ
docker cp web:/etc/nginx/nginx.conf ./nginx.conf
docker save -o images.tar sample:local
docker load -i images.tar
docker load < images.tar

# 対象のwslc JSONに該当フィールドがある場合に利用できる簡易テンプレート
docker inspect --format '{{.State.Running}}' web

# 実行せず、変換後の引数をJSONで確認
docker-wslc dry-run run --rm -v "$PWD:/work:ro" alpine:3.22 ls /work
```

上記は独立した使用例です。`web` を削除した後で `cp` や `inspect` を使う場合は再作成してください。

## 実装した互換処理

| 入力・機能 | このラッパーの処理 |
|---|---|
| `ps` / `images` / `rm` / `rmi` | `container list` / `image list` / `container remove` / `image remove` へ変換 |
| `run` / `create` / `exec` | Dockerオプションを解析し、イメージ・コンテナー名以降のコマンド引数はそのまま渡す |
| `-it` / `-aq` / `-eKEY=value` | 短縮・結合オプションを正規化 |
| `-v` / `--mount` | ホスト側のパスを変換。名前付きボリュームとコンテナー内パスは維持 |
| `build` | コンテキスト・`-f`・`--iidfile`・ファイル型secret・出力ファイルのパスを変換 |
| `Dockerfile` / `Containerfile` の併存 | `-f` 未指定時はDockerと同じくDockerfileを選択 |
| `-e NAME` / `--build-arg NAME` | Ubuntuの環境変数を明示値に変換 |
| `--env-file` | Ubuntuで読み込み、環境変数引数へ展開。明示した `-e` を優先 |
| `cp` | ローカル側だけ変換。`CONTAINER:PATH` と末尾 `/.` は維持 |
| `save -o` / `load -i` / `export -o` / `import FILE` | ホストファイルのパスを変換 |
| `load < archive.tar` / `load -i -` | 非公開の一時ディレクトリーにディスクへストリーム保存し、wslcの `load --input` に接続、終了後削除 |
| `stop` / `restart` の `--time` / `--timeout` | wslcの各サブコマンドに対応するオプション名へ変換 |
| `--format '{{.Field}}'` | wslcのJSON出力を読み、単純なフィールド参照を表示 |
| 標準入出力・TTY・終了コード | 通常はexecでwslcへ置換。アーカイブ入力とテンプレート処理は子プロセス経由 |
| `compose` / `docker-compose` | 同梱のwslc-composeへ引数を渡す |

`network`、`volume`、`image`、`container` の対応するサブコマンドも使えます。
完全なコマンドと受け付けるオプション名は `docker-wslc capabilities` で表示します。
一覧はMicrosoftの公開ソースを2026-10-06に確認したものです。インストールされているwslcが古い場合は、
一覧にある操作でもwslc側が拒否することがあります。

## パス変換

既定では `wslpath -w` を利用します。

| Ubuntuのパス | Windows側のパスの例 |
|---|---|
| `/mnt/c/work/app` | `C:\work\app` |
| `/home/me/app` | `\\wsl.localhost\Ubuntu\home\me\app`（ディストリビューション名などは環境依存） |
| `./config` | カレントディレクトリーを基準に絶対化後、変換 |

WindowsドライブのパスとUNCパスは、そのまま渡します。
パス変換だけではファイル共有の可否や権限・ファイル所有者・性能は保証できません。
特にUbuntuのファイルシステムを実際にマウントできるかは、手元のwslcで `scripts/smoke-test.sh` を実行して確認してください。
このパッケージ自体にはNFSサーバーやファイル同期処理は含みません。

`WSLC_DOCKER_PATH_MODE=native` はLinuxパスを受ける自作バックエンドやモック向けです。
通常の `wslc.exe` を使う場合は既定の `windows` を使用してください。
Linux向けの他のラッパーを間に入れる場合は、`container run` などのグループ形式も扱える必要があります。
既存の `wslc-remote` との組み合わせは未検証です。

## Compose

同梱の `wslc-compose` がYAMLを読み込み、wslc向けのサービス操作を実行します。`docker compose` と `docker-compose` の両方から利用できます。Compose実装は上流の [bacarndiaye/wslc-compose](https://github.com/bacarndiaye/wslc-compose) を固定コミットで同梱し、MITライセンスもパッケージに収録します（[UPSTREAM.md](UPSTREAM.md)）。追加ダウンロードは不要です。

```bash
# Windows側でwslcが動作するパスを指定する場合
export WSLC_COMPOSE_BIN='/mnt/c/Program Files/WSL/wslc.exe'

docker compose -f examples/compose.yaml up -d
docker compose -f examples/compose.yaml ps
docker compose -f examples/compose.yaml down
```

`WSLC_COMPOSE_BIN` が未指定の場合、同梱ComposeはPATH上の `wslc.exe` / `wslc` と標準のWindowsインストール先を自動検出します。カスタム配置の場合は `WSLC_COMPOSE_BIN` で指定してください。Compose仕様の対応範囲や各機能の挙動は同梱実装のREADMEにも記載されています。

Debianパッケージのインストールだけで `docker compose`、`docker-compose`、`wslc-compose` を利用できます。

## 互換範囲の境界

- **Docker Engine API / docker.sock / DOCKER_HOSTは提供しません。** TestcontainersやAPI接続型のツールはそのままでは動きません。
- `buildx`、Swarm、Docker context、`system prune`、`wait`、`commit`、`history` など、この実装の一覧にないコマンドは未対応です。
- `--restart`、`--privileged`、`--platform` など、対応一覧にないオプションはエラーにします。無視して成功扱いにしません。
- JSONの項目名・型、テーブルの列・文言はDockerと同一とは限りません。出力を解析する既存スクリプトは確認が必要です。
- テンプレートは `{{.Field}}`、`{{.Nested.Field}}`、`{{json .Field}}` と前後の文字列だけ対応。`range`、`index`、条件分岐、`table` テンプレートは未対応です。wslcのJSONにない項目はエラーにします。
- `--format json` はwslcのJSONをそのまま出力します。行ごとのJSONか配列かもwslcに依存します。
- URL/Git/標準入力のビルドコンテキストは未対応です。ローカルディレクトリーと `build -f - DIR` は対応します。
- `cp -` のtarストリーム、`import -`、環境変数を直接使うbuild secret、`--mount` の伝播設定などは未対応です。
- `-v` のモードは `ro` / `rw` に限定します。ファイル作成、所有権、権限、ボリュームドライバーの細かな挙動はwslc依存です。
- `-e NAME` でUbuntu側にNAMEがない場合、Windowsの同名変数を誤用しないようエラーにします。イメージ内環境変数のunsetは再現しません。
- envファイルはDocker run形式として扱い、引用符や `$VAR`、`$(...)` を評価しません。Composeの.env補間とは異なります。
- 明示値 `--rm=false` などは未対応です。フラグ省略に直してください。
- `DOCKER_HOST`、`DOCKER_CONTEXT`、`DOCKER_CONFIG`、TLS設定が環境変数に残っていれば停止します。ローカルwslcを使う意図を確認して明示的に解除してください。Windows側のwslc認証設定を利用するため、Dockerの既存ログイン情報は移行しません。
- 32KB程度のWindowsコマンドライン制約により、大量の環境変数・長い引数は失敗する可能性があります。`--env-file` も引数へ展開されます。

ネイティブwslcの機能を直接呼びたい場合は `docker-wslc raw ...` を使えます。
この経路ではDocker互換処理・パス変換・Docker環境変数の確認を行いません。

## 設定

| 環境変数 | 内容 |
|---|---|
| `WSLC_DOCKER_BIN` | wslcの実行ファイル1個のパス。空白を含むパス可。シェルコマンドや追加引数は不可 |
| `WSLC_DOCKER_PATH_MODE` | `windows`（既定）または `native` |
| `WSLC_DOCKER_COMPOSE_BIN` | 任意のWSLC用Compose実装の実行ファイル |

通常のコマンドでは引数をログに出しません。
dry-runでは `--env`、`--build-arg`、`--password` の値を伏せます。
コンテナーに渡す任意のコマンド文字列などに秘密情報を含めた場合、その内容までは判定できません。

## 検証

```bash
# wslc不要の単体・プロセス・インストーラーテスト
bash scripts/test.sh

# 実際のWSLコンテナーで確認。イメージを取得し、一時的なコンテナー等を作成します。
bash scripts/smoke-test.sh
```

ラッパーのテストに加え、同梱Composeの上流テストとdebのインストール・コマンド登録・競合・アップグレード・削除をGitHub Actionsで検証します。
テスト対象には空白・日本語・引用符を含む引数、バイナリ入出力、終了コード、環境変数優先順位、
stdinのアーカイブ処理、Composeへの転送、インストール・再インストール・削除を含みます。
**作成環境にはWindows/WSL/wslc実機がないため、実機テストは未実施です。**
同梱smoke-testは、ビルド、読み取り専用bind、名前付きボリューム、exec、cp、save/loadを確認し、
自身の一時リソースを後片付けします。ベースイメージやビルドキャッシュは残る場合があります。
対話TTYは `docker run --rm -it alpine:3.22 sh` で別途確認してください。

## 削除

```bash
sudo apt remove wslc-docker
```

apt/dpkgがパッケージ本体と `/usr/bin` のコマンドリンクを削除します。Windows側のWSL、イメージ、コンテナー、ボリューム、認証情報は削除しません。

## ソースからのユーザー単位インストール（任意）

debを使わずに、利用者のホームディレクトリーだけに導入したい場合に使います。こちらはPython 3とPyYAMLを事前に用意し、PATHを設定する必要があります。

```bash
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
# この方法で導入したものを削除
bash uninstall.sh
```

導入先は `~/.local/share/wslc-docker`、コマンドは `~/.local/bin` です。`--prefix` で変更できます。既存の同名コマンドは上書きせずに終了します。

## 構成

- `bin/docker`：Docker形式のCLI入口
- `bin/docker-compose`：Compose用の旧形式入口
- `bin/docker-wslc`：診断、dry-run、対応一覧、ネイティブ呼び出し
- `lib/wslc_docker.py`：引数・パス・環境変数の変換本体
- `lib/options.json`：wslcの公開ソースから確認したコマンド・オプション定義
- `install.sh` / `uninstall.sh` / `scripts/manage_install.py`：導入と削除
- `scripts/test.sh` / `tests/`：自動テスト
- `scripts/smoke-test.sh`：WSL実機確認
- `examples/`：DockerfileとComposeの例

## 参照した一次資料

確認日：2026-10-06。公開ソースのmasterブランチと配布済みwslcの機能が一致するとは限りません。

- [Microsoft Learn：WSL container](https://learn.microsoft.com/en-us/windows/wsl/wsl-container)
- [Microsoft Learn：Get started with containers on WSL](https://learn.microsoft.com/en-us/windows/wsl/tutorials/wsl-containers)
- [Microsoft WSL：CLI command definitions](https://github.com/microsoft/WSL/tree/master/src/windows/wslc/commands)
- [Microsoft WSL：ArgumentDefinitions.h](https://github.com/microsoft/WSL/blob/master/src/windows/wslc/arguments/ArgumentDefinitions.h)
- [Microsoft WSL：ImageTasks.cpp（loadのstdin対応状況）](https://github.com/microsoft/WSL/blob/master/src/windows/wslc/tasks/ImageTasks.cpp)
- [Microsoft WSL：ImageService.cpp（Dockerfile選択・ビルドコンテキスト）](https://github.com/microsoft/WSL/blob/master/src/windows/wslc/services/ImageService.cpp)
- [Microsoft WSL：Docker Engine API互換の要望 #40976](https://github.com/microsoft/WSL/issues/40976)

ライセンス：MIT（同梱LICENSE）。
