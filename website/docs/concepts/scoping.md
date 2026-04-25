# Scoping

Remembr is multi-tenant by default. Reads and writes are scoped from the authenticated API key and narrowed further by session, user, team, or agent context.

## Scope layers

- Organization scope is always enforced.
- Team, user, and agent scope can narrow visibility further.
- Session scope is the most common application-level filter.

## Practical effect

- One organization's memory cannot leak into another organization's search results.
- Soft-deleted records stay hidden even if a query would otherwise match them.
- Sessions inherit the effective writable scope at creation time.

## Recommendation

Use tags for semantic grouping such as `topic:billing` or `kind:feedback`, but rely on scope for security boundaries.

