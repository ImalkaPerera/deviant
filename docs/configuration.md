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

A single word can also be written as a string: `"auth_words": "tenant_access"`. If the file is
not valid JSON, or `auth_words` is neither a list nor a string, the scan says so on stderr and
does not use it, rather than reporting your guarded routes as unprotected without a word.
