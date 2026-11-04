package com.example.internetarchive

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import java.net.URLEncoder

/*
 * Internet Archive public API, no Cloudstream types, so it is unit tested on the JVM.
 *
 *   search:    https://archive.org/advancedsearch.php?q=...&fl[]=...&output=json
 *   metadata:  https://archive.org/metadata/{identifier}
 *   file:      https://archive.org/download/{identifier}/{file name}
 *   thumbnail: https://archive.org/services/img/{identifier}
 *
 * Archive JSON is loosely typed: a field can be a string, a number or a list of
 * strings depending on the item, so every read goes through the tolerant helpers below.
 */

data class ArchiveItem(
    val identifier: String,
    val title: String,
    val year: Int?,
) {
    val detailsUrl get() = "${ArchiveApi.BASE}/details/$identifier"
    val posterUrl get() = ArchiveApi.thumbnail(identifier)
}

data class ArchiveVideo(
    val url: String,
    val label: String,
    val height: Int?,
    val isOriginal: Boolean,
)

data class ArchiveSubtitle(val url: String, val label: String)

data class ArchiveDetail(
    val identifier: String,
    val title: String,
    val description: String?,
    val year: Int?,
    val tags: List<String>,
    val videos: List<ArchiveVideo>,
    val subtitles: List<ArchiveSubtitle>,
)

object ArchiveApi {
    const val BASE = "https://archive.org"

    /** Home rows: collection id to row title. All are collections of public-domain films. */
    val COLLECTIONS: List<Pair<String, String>> = listOf(
        "feature_films" to "Uzun Metraj Filmler",
        "Film_Noir" to "Kara Filmler",
        "SciFi_Horror" to "Bilim Kurgu ve Korku",
        "comedy_films" to "Komedi",
        "silent_films" to "Sessiz Filmler",
        "classic_cartoons" to "Klasik Çizgi Filmler",
        "classic_tv" to "Klasik TV",
    )

    /** Search runs over all of these collections. */
    private val SEARCH_COLLECTIONS = COLLECTIONS.map { it.first }

    const val PAGE_SIZE = 50

    /** Formats Android's player plays reliably, best first. Ogg/Matroska/MPEG2 are skipped. */
    private val VIDEO_FORMATS = listOf("h.264", "h.264 IA", "MPEG4", "512Kb MPEG4")

    private val SUBTITLE_FORMATS = setOf("SubRip", "Web Video Text Tracks")

    private val mapper = ObjectMapper()

    fun thumbnail(identifier: String) = "$BASE/services/img/${encodePath(identifier)}"

    fun collectionUrl(collection: String, page: Int): String =
        searchUrl("collection:(${escape(collection)}) AND mediatype:(movies)", page)

    fun searchQueryUrl(query: String, page: Int = 1): String {
        val q = escape(query.trim())
        val collections = SEARCH_COLLECTIONS.joinToString(" OR ") { escape(it) }
        return searchUrl("collection:($collections) AND mediatype:(movies) AND (title:($q) OR subject:($q))", page)
    }

    private fun searchUrl(q: String, page: Int): String =
        "$BASE/advancedsearch.php?q=${enc(q)}" +
            "&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=year" +
            "&sort%5B%5D=${enc("downloads desc")}" +
            "&rows=$PAGE_SIZE&page=${page.coerceAtLeast(1)}&output=json"

    fun metadataUrl(identifier: String) = "$BASE/metadata/${encodePath(identifier)}"

    /** "https://archive.org/details/abc/xyz" or "abc" -> "abc" */
    fun identifierFrom(urlOrId: String): String? {
        val id = urlOrId.trim().substringAfter("/details/", urlOrId.trim()).substringBefore('/')
            .substringBefore('?').substringBefore('#')
        return id.takeIf { it.isNotEmpty() && ID.matches(it) }
    }

    // ------------------------------------------------------------------ parsing

    /** Returns items and whether more pages exist. */
    fun parseSearch(json: String, page: Int = 1): Pair<List<ArchiveItem>, Boolean> {
        val response = runCatching { mapper.readTree(json) }.getOrNull()?.get("response")
            ?: return emptyList<ArchiveItem>() to false
        val items = response.get("docs")?.mapNotNull { doc ->
            val id = doc.text("identifier")?.takeIf { ID.matches(it) } ?: return@mapNotNull null
            ArchiveItem(id, doc.text("title") ?: id, doc.text("year")?.let(::yearOf))
        }.orEmpty()
        val total = response.get("numFound")?.asInt() ?: 0
        return items to (page * PAGE_SIZE < total)
    }

    fun parseMetadata(json: String): ArchiveDetail? {
        val root = runCatching { mapper.readTree(json) }.getOrNull() ?: return null
        val meta = root.get("metadata") ?: return null
        val id = meta.text("identifier")?.takeIf { ID.matches(it) } ?: return null
        if (meta.text("mediatype")?.let { it != "movies" } == true) return null

        val files = root.get("files")?.toList().orEmpty()
        val videos = files.mapNotNull { f ->
            val name = f.text("name") ?: return@mapNotNull null
            val format = f.text("format") ?: return@mapNotNull null
            val rank = VIDEO_FORMATS.indexOf(format).takeIf { it >= 0 } ?: return@mapNotNull null
            val height = f.text("height")?.toIntOrNull()?.takeIf { it > 0 }
            val original = f.text("source") == "original"
            rank to ArchiveVideo(
                url = downloadUrl(id, name),
                label = listOfNotNull(height?.let { "${it}p" }, format, if (original) "orijinal" else null)
                    .joinToString(" · "),
                height = height,
                isOriginal = original,
            )
        }
            // best format first, then larger picture
            .sortedWith(compareBy<Pair<Int, ArchiveVideo>> { it.first }.thenByDescending { it.second.height ?: 0 })
            .map { it.second }
            .distinctBy { it.url }

        val subtitles = files.mapNotNull { f ->
            val name = f.text("name") ?: return@mapNotNull null
            if (f.text("format") !in SUBTITLE_FORMATS) return@mapNotNull null
            ArchiveSubtitle(downloadUrl(id, name), subtitleLabel(name))
        }

        return ArchiveDetail(
            identifier = id,
            title = meta.text("title") ?: id,
            description = meta.texts("description").joinToString("\n").let(::stripHtml).ifBlank { null },
            year = (meta.text("year") ?: meta.text("date"))?.let(::yearOf),
            tags = meta.texts("subject").flatMap { it.split(';', ',') }.map { it.trim() }
                .filter { it.isNotEmpty() && it.length <= 40 }.distinct().take(12),
            videos = videos,
            subtitles = subtitles,
        )
    }

    // ------------------------------------------------------------------ helpers

    fun downloadUrl(identifier: String, fileName: String) =
        "$BASE/download/${encodePath(identifier)}/" + fileName.split('/').joinToString("/") { encodePath(it) }

    /** First string of a field that may be a string, a number or an array. */
    private fun JsonNode.text(field: String): String? = texts(field).firstOrNull()

    private fun JsonNode.texts(field: String): List<String> {
        val node = get(field) ?: return emptyList()
        val values = if (node.isArray) node.toList() else listOf(node)
        return values.filter { it.isValueNode }.map { it.asText().trim() }.filter { it.isNotEmpty() }
    }

    private fun yearOf(s: String): Int? = YEAR.find(s)?.value?.toIntOrNull()

    private fun subtitleLabel(fileName: String): String {
        val base = fileName.substringAfterLast('/').substringBeforeLast('.')
        val lang = base.substringAfterLast('.', "").takeIf { it.length in 2..3 }
        return lang?.uppercase() ?: "Altyazı"
    }

    private fun stripHtml(s: String): String =
        s.replace(Regex("<br\\s*/?>", RegexOption.IGNORE_CASE), "\n")
            .replace(Regex("<[^>]+>"), "")
            .replace("&amp;", "&").replace("&quot;", "\"").replace("&#39;", "'")
            .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
            .lines().joinToString("\n") { it.trim() }.replace(Regex("\n{3,}"), "\n\n").trim()

    /** Lucene special characters are escaped so a query cannot change the search filter. */
    private fun escape(s: String): String = s.replace(LUCENE_SPECIAL) { "\\" + it.value }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    private fun encodePath(s: String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

    private val ID = Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,99}") // must not start with "." (no "..")
    private val YEAR = Regex("(18|19|20)\\d{2}")
    private val LUCENE_SPECIAL = Regex("""[+\-!(){}\[\]^"~*?:\\/&|]""")
}
