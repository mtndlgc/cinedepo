rootProject.name = "CloudstreamPlugins"

// Every top-level directory that contains a build.gradle.kts is a plugin module.
// To temporarily skip a plugin, add its directory name here.
val disabled = listOf<String>()

File(rootDir, ".").eachDir { dir ->
    if (dir.name !in disabled && File(dir, "build.gradle.kts").exists()) {
        include(dir.name)
    }
}

fun File.eachDir(block: (File) -> Unit) {
    listFiles()?.filter { it.isDirectory }?.forEach { block(it) }
}
