# Configuration

Optional settings, kept in your project.

Optional. Create `.deviant/config.json` in the scanned project:

```json
{
  "auth_words": ["tenant_access", "require_org_member"]
}
```

`auth_words` adds names that should count as auth dependencies. Use it when the scan reports a
route as unprotected but a dependency listed under that exception does check who is calling. A
whole word in the dependency's name is enough, for example `tenant_access` for
`get_tenant_access`.
