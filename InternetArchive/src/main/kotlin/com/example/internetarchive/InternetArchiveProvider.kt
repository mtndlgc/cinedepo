package com.example.internetarchive

import com.lagradost.cloudstream3.HomePageResponse
import com.lagradost.cloudstream3.LoadResponse
import com.lagradost.cloudstream3.MainAPI
import com.lagradost.cloudstream3.MainPageRequest
import com.lagradost.cloudstream3.SearchResponse
import com.lagradost.cloudstream3.SubtitleFile
import com.lagradost.cloudstream3.TvType
import com.lagradost.cloudstream3.app
import com.lagradost.cloudstream3.mainPageOf
import com.lagradost.cloudstream3.newHomePageResponse
import com.lagradost.cloudstream3.newMovieLoadResponse
import com.lagradost.cloudstream3.newMovieSearchResponse
import com.lagradost.cloudstream3.utils.ExtractorLink
import com.lagradost.cloudstream3.utils.ExtractorLinkType
import com.lagradost.cloudstream3.utils.Qualities
import com.lagradost.cloudstream3.utils.newExtractorLink

/**
 * Public-domain films from the Internet Archive (archive.org), via its JSON API.
 * See [ArchiveApi] for the endpoints and parsing.
 */
class InternetArchiveProvider : MainAPI() {
    override var mainUrl = ArchiveApi.BASE
    override var name = "Internet Archive"
    override var lang = "en"
    override val hasMainPage = true
    override val hasDownloadSupport = true
    override val supportedTypes = setOf(TvType.Movie)

    override val mainPage = mainPageOf(*ArchiveApi.COLLECTIONS.toTypedArray())

    private suspend fun getText(url: String): String = app.get(url, timeout = 30L).text

    override suspend fun getMainPage(page: Int, request: MainPageRequest): HomePageResponse {
        val (items, hasNext) = ArchiveApi.parseSearch(getText(ArchiveApi.collectionUrl(request.data, page)), page)
        return newHomePageResponse(request.name, items.map { it.toSearchResponse() }, hasNext)
    }

    override suspend fun search(query: String): List<SearchResponse> {
        if (query.isBlank()) return emptyList()
        return ArchiveApi.parseSearch(getText(ArchiveApi.searchQueryUrl(query))).first.map { it.toSearchResponse() }
    }

    override suspend fun load(url: String): LoadResponse? {
        val id = ArchiveApi.identifierFrom(url) ?: return null
        val detail = ArchiveApi.parseMetadata(getText(ArchiveApi.metadataUrl(id))) ?: return null
        // `data` for loadLinks is the identifier; links are resolved from the metadata again.
        return newMovieLoadResponse(detail.title, url, TvType.Movie, detail.identifier) {
            posterUrl = ArchiveApi.thumbnail(detail.identifier)
            plot = detail.description
            year = detail.year
            tags = detail.tags
        }
    }

    override suspend fun loadLinks(
        data: String,
        isCasting: Boolean,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit,
    ): Boolean {
        val id = ArchiveApi.identifierFrom(data) ?: return false
        val detail = ArchiveApi.parseMetadata(getText(ArchiveApi.metadataUrl(id))) ?: return false

        detail.subtitles.forEach { subtitleCallback(SubtitleFile(it.label, it.url)) }
        detail.videos.forEach { v ->
            callback(
                newExtractorLink(
                    source = name,
                    name = "$name ${v.label}",
                    url = v.url,
                    type = ExtractorLinkType.VIDEO,
                ) {
                    referer = "$mainUrl/"
                    // Qualities values are picture heights (P480 = 480, ...).
                    quality = v.height ?: Qualities.Unknown.value
                }
            )
        }
        return detail.videos.isNotEmpty()
    }

    private fun ArchiveItem.toSearchResponse(): SearchResponse =
        newMovieSearchResponse(title, detailsUrl, TvType.Movie) {
            this.posterUrl = this@toSearchResponse.posterUrl
            this.year = this@toSearchResponse.year
        }
}
