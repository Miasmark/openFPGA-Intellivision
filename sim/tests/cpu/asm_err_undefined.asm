; An undefined symbol is an error.
;! asm-error undefined symbol 'nowhere'
        ORG     $5000
start:  B       nowhere
