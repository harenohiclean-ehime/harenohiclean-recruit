# harenohiclean-recruit

ハレノヒクリーンの業務委託募集ページ（試作・noindex）。`sites/harenohiclean/data.yml` を正本に、`docs/` へ静的HTMLを生成します。`docs/` は手で編集しません。

## ビルド

```sh
pip install pyyaml
python3 generator/build.py
```

次のどれかに当たるとビルドは失敗し、`docs/` は更新されません。

- `generator/terms.yml` のNG語が生成物に含まれている
- `data.yml` にない数値がページに含まれている
- 確認日から60日を過ぎた必須の数値がある（実績は失敗にせず、ページから隠す）
- 試算の計算が合わない、noindex や JobPosting の内容が決めごとと違う

## 公開前に変えるところ

- 検索に出す：`data.yml` の `site.noindex` を `false` にして再ビルド
- 申込フォームを動かす：`docs/apply/config.js` の `APPLY_ENDPOINT` に送信先を入れる（再ビルドしても消えません）
