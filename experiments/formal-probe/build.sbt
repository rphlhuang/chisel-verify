// Self-contained sbt project for the LTL capability probe. Intentionally
// decoupled from the root build so it never compiles as part of the main
// project and can be dropped/gitignored without touching main.
ThisBuild / scalaVersion := "2.13.18"

val chiselVersion = "7.13.0"

lazy val root = (project in file("."))
  .settings(
    name := "formal-probe",
    libraryDependencies += "org.chipsalliance" %% "chisel" % chiselVersion,
    scalacOptions ++= Seq("-Ymacro-annotations"),
    addCompilerPlugin("org.chipsalliance" % "chisel-plugin" % chiselVersion cross CrossVersion.full),
  )