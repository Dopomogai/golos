---
@purpose: "How to preview and deploy the static golos product page under site/."
@why: "Connects PRODUCT_PAGE.md copy to the dependency-free site layout and local preview path."
@role: reference
@stability: evolving
@tags: [golos, site, product-page, static, deploy]
related_docs: [docs/PRODUCT_PAGE.md, RELEASE_CHECKLIST.md]
---
# golos product page

Static, dependency-free product page mapped from `docs/PRODUCT_PAGE.md`.

Preview locally:

```sh
python3 -m http.server 8000 --directory site
```

Then open <http://localhost:8000>. Deploy the contents of this directory as
the `/golos` route (or as its own static site). Repository and installer links
target `andriisolovei/golos`; the installer URL becomes live when the signed
`golos-0.2.0.dmg` is attached to the GitHub `v0.2.0` release.
