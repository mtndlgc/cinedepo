// Bump this on every release: the app updates a plugin only when the version grows.
version = 3

cloudstream {
    // TODO: sağlayıcınızı tanımlayın.
    description = "Genel amaçlı HTML sağlayıcı şablonu. Erişim izniniz olan bir siteye uyarlayın."
    authors = listOf("mtndlgc")
    language = "tr"

    /**
     * 0: Down
     * 1: Ok
     * 2: Slow
     * 3: Beta only
     */
    status = 1

    // Must match TvType names used in the provider (Movie, TvSeries, Anime, Documentary, ...).
    tvTypes = listOf("Movie", "TvSeries")

    // TODO: set your site's domain; %size% is replaced by the app.
    iconUrl = "https://www.google.com/s2/favicons?domain=example-site.com&sz=%size%"
}
