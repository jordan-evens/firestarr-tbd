USER=$(gh api user | jq -r ".login")
gh act -a ${USER} -s GHCR_TOKEN=${GHCR_TOKEN} -j build-test-publish $*
gh act -a ${USER} -s GITHUB_TOKEN=${GITHUB_TOKEN} -j doxygen $*
