git status -s | egrep "^.[M]" | cut -c4- | xargs -0 | egrep .

