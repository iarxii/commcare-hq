hqDefine("cloudcare/js/spec/markdown_spec", function () {
    describe('Markdown', function () {
        let render = hqImport('cloudcare/js/markdown').render;

        describe('Markdown', function () {
            it('should render without error', function () {
                assert.equal(render("plain text"), "<p>plain text</p>\n");
            });

            it('should render links with _blank target', function () {
                assert.equal(
                    render("[link](http://example.com)"),
                    "<p><a href=\"http://example.com\" target=\"_blank\">link</a></p>\n"
                );
            });

            it('should render headings with tabindex set', function () {
                assert.equal(
                    render("# heading"),
                    "<h1 tabindex=\"0\">heading</h1>\n"
                );
            });

            it('should render newlines as breaks', function () {
                assert.equal(
                    render("line 1\nline 2"),
                    "<p>line 1<br>\nline 2</p>\n"
                );
            });

            it('should render encoded newlines as breaks', function () {
                assert.equal(
                    render("line 1&#10;line 2"),
                    "<p>line 1<br>\nline 2</p>\n"
                );
            });
        });
    });
});
