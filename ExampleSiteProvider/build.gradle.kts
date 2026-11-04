// Bump this on every release: the app updates a plugin only when the version grows.
version = 1

cloudstream {
    // TODO: describe your provider.
    description = "Generic HTML provider template. Point it at a site you are allowed to scrape."
    authors = listOf("YOUR_NAME")
    language = "en"

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
