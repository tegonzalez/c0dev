git status -s | egrep "^[AM]" | cut -c4- | xargs -0 | egrep .

