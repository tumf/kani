## MODIFIED Requirements

### Requirement: Strict モード

`strict=True` の場合、不完全な設定は例外を発生させなければならない (SHALL)。また hot reload はこの strict 検証を通過した設定のみを適用しなければならない (SHALL)。

#### Scenario: hot reload で strict 検証済み設定のみ適用される

- GIVEN 動作中の proxy が hot reload 用に config を再読込する
- WHEN 新しい config が `load_config(..., strict=True)` に成功する
- THEN proxy はその設定を reload 候補として使える
- AND strict 検証に失敗した config は active state に適用されない
