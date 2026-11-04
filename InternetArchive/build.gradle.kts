// Bump this on every release: the app updates a plugin only when the version grows.
version = 1

cloudstream {
    description = "Internet Archive'daki kamu malı (telif süresi dolmuş) filmler, çizgi filmler ve TV yayınları."
    authors = listOf("mtndlgc")
    // Most items in these collections are in English.
    language = "en"

    /**
     * 0: Down
     * 1: Ok
     * 2: Slow
     * 3: Beta only
     */
    status = 1

    tvTypes = listOf("Movie")

    iconUrl = "https://www.google.com/s2/favicons?domain=archive.org&sz=%size%"
}
