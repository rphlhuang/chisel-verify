ThisBuild / scalaVersion := "2.13.18"
ThisBuild / version      := "0.1.0"
ThisBuild / organization := "com.github.rphlhuang"
ThisBuild / logLevel     := Level.Info
Test / testOptions       += Tests.Argument(TestFrameworks.ScalaTest, "-oF")


val chiselVersion    = "7.13.0"
val scalatestVersion = "3.2.19"

lazy val root = (project in file("."))
  .settings(
    name := "chisel-verify",
    libraryDependencies ++= Seq(
      "org.chipsalliance" %% "chisel"     % chiselVersion,
      "org.scalatest"     %% "scalatest"  % scalatestVersion % "test",
    ),
    Compile / unmanagedSourceDirectories ++= Seq(
      baseDirectory.value / "chisel-axi-utils" / "src" / "main" / "scala",
      baseDirectory.value / "berkeley-hardfloat" / "hardfloat" / "src" / "main" / "scala",
      // baseDirectory.value / "rial" / "src" / "main" / "scala",
    ),
    // TEMP [Claude]: Axi4LiteCRC is WIP + depends on the broken rial submodule; exclude so the mallet flow compiles
    Compile / unmanagedSources / excludeFilter := HiddenFileFilter || "Axi4LiteCRC.scala",
    scalacOptions ++= Seq(
      "-language:reflectiveCalls",
      "-deprecation",
      "-feature",
      "-Xcheckinit",
      "-Ymacro-annotations",
    ),
    addCompilerPlugin("org.chipsalliance" % "chisel-plugin" % chiselVersion cross CrossVersion.full),
  )