USER=$(gh api user | jq -r ".login")
gh act -a ${USER} -s GHCR_TOKEN=${GHCR_TOKEN} -j image-build-test-publish $*
gh act -a ${USER} -s GHCR_TOKEN=${GHCR_TOKEN} -j doxygen $*
