#!groovy

@Library('pipelib')
import org.veupathdb.lib.Builder

node('podbuild') {
  def builder = new Builder(this)

  builder.gitClone()
  builder.buildContainers([
    [ name: 'wdk-mcp' ],
    [ name: 'research-mcp', dockerfile: 'Dockerfile.research' ]
  ])
}
