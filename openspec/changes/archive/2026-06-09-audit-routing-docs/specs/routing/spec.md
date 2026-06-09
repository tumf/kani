## MODIFIED Requirements

### Requirement: プロバイダ解決優先順位

プロバイダは 3 段階の優先順位で解決されなければならない (SHALL)。Routing documentation MUST clearly describe this provider resolution precedence and MUST clarify that configured model IDs are sent literally to the selected provider.

#### Scenario: プロバイダ解決の優先順位

- GIVEN モデルエントリにプロバイダ指定がある場合
- THEN そのプロバイダを使用する (最優先)
- GIVEN モデルエントリにプロバイダ指定がなく、ティア設定にプロバイダ指定がある場合
- THEN ティアレベルのプロバイダを使用する
- GIVEN いずれも指定がない場合
- THEN `default_provider` を使用する

#### Scenario: Model IDs are literal provider model IDs

**Given** an operator configures a tier `primary` or `fallback` model ID
**When** kani sends a routed request upstream
**Then** kani MUST send the configured model ID literally to the selected provider
**And** documentation MUST NOT imply an unsupported `provider/model` parsing syntax unless such parsing is actually implemented
