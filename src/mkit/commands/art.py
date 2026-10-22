"""Store art: screenshots and feature graphic from captures and captions (see mkit/art.py)."""
from .. import art
from ..registry import Arg, command, group

group('art', 'store screenshots and feature graphic, built from captures and captions')

CODES = Arg('codes', 'listing codes (default: every captions file)', kind='positional', nargs='*')


def _codes(design, args):
    codes = args.codes or design.codes()
    unknown = [c for c in codes if c not in design.codes()]
    if unknown:
        from ..errors import NotFound
        raise NotFound(f'no captions for {", ".join(unknown)}',
                       hint=f'Captions live in {design.dir / "captions"}/<code>.json.', code='NO_CAPTIONS')
    return codes


def _coverage(project, design):
    """Listing codes with no captions, and captions no listing uses."""
    locales = project.section('store').get('locales') or {}
    if not locales:
        return [], []
    have = set(design.codes())
    return sorted(set(locales) - have), sorted(have - set(locales))


@command('art init', 'Set up store art: the art folder, [art] in mkit.toml, .gitignore lines',
         risk='write', examples=('mkit art init',))
def art_init(ctx, args):
    """Creates <dir>/shots/, <dir>/captions/en.json and <dir>/art.toml from the
    starter files, adds [art] to mkit.toml and keeps the built images out of
    git. Only what is missing is written."""
    done = art.init(ctx.project)
    if not ctx.out.json:
        for line in done or ['already set up; nothing to do']:
            ctx.out.line(f'  {line}')
        ctx.out.line('Next: captures in shots/, words in captions/en.json, slides in art.toml, '
                     'then `mkit art check` and `mkit art build`.')
    return {'done': done}


@command('art check', 'Line counts of every language against the reference (text only, no images)',
         risk='read', needs=('art',),
         examples=('mkit art check', 'mkit art check de ar ja'), args=(CODES,))
def art_check(ctx, args):
    """Each caption block must wrap to as many lines as in the reference
    language and stay inside its box; each file must have the reference's
    keys, one [accent] per title and no dashes, arrows or bullets. The
    reference itself, when named, is held to its boxes and line caps (a pop
    title is at most two lines; a pill stays on the page). The pages are laid
    out in the browser but no image is made, so a translation can be fitted
    in seconds."""
    design = art.Design(ctx.project)
    codes = _codes(design, args)
    out = ctx.out
    out.start(f'{ctx.project.name} store art check', 1, f'{len(codes)} language(s), against {design.reference}')
    out.step('Lay out every page')

    def report(code, problems):
        if not out.json:
            if problems:
                out.line(f'  {code}:', 'yellow')
                for p in problems:
                    out.line(f'    {p}', 'yellow')
            else:
                out.line(f'  {code}: OK')

    results = art.check(design, codes, on_result=report)
    out.done()
    ref = results.pop('_reference')
    bad = {c: p for c, p in results.items() if p}
    no_captions, unused = _coverage(ctx.project, design)
    if not out.json:
        if no_captions:
            out.line(f'  listing codes with no captions (they get no art): {", ".join(no_captions)}', 'yellow')
        if unused:
            out.line(f'  captions no listing uses: {", ".join(unused)}', 'yellow')
    if bad:
        ctx.exit_code = 1
    out.finish(f'{len(results) - len(bad)} of {len(results)} fit' if results else 'only the reference to check')
    return {'reference': design.reference,
            'reference_lines': {stem: {k: v['lines'] for k, v in blocks.items() if k != 'head'}
                                for stem, blocks in ref.items()},
            'languages': results, 'no_captions': no_captions, 'unused_captions': unused}


@command('art build', 'Draw the screenshots and feature graphic for each language',
         risk='write', needs=('art',),
         examples=('mkit art build', 'mkit art build en ar', 'mkit art build en --keep-pages'),
         args=(CODES, Arg('keep_pages', 'keep the HTML pages and print where', kind='flag')))
def art_build(ctx, args):
    """Writes <art_dir>/screenshots/<code>/01_<slide>.png ... and
    <art_dir>/feature/<code>.png, the files `mkit listing plan --images-only`
    compares with Play. Nothing is uploaded."""
    design = art.Design(ctx.project)
    codes = _codes(design, args)
    out = ctx.out
    out.start(f'{ctx.project.name} store art', 1, f'{len(codes)} language(s)')
    out.step('Draw the pages')

    def report(code, files):
        if not out.json:
            out.line(f'  {code}: {len(files)} images')

    written, kept = art.build(design, codes, keep_pages=args.keep_pages, on_result=report)
    out.done()
    if not out.json:
        out.line(f'  screenshots: {design.out / "screenshots"}')
        out.line(f'  feature graphics: {design.out / "feature"}')
        if kept:
            out.line(f'  pages kept in {kept}')
        out.line('Upload: `mkit listing plan --images-only`, then `mkit listing apply --images-only`.')
    out.finish(f'{sum(len(f) for f in written.values())} images for {len(written)} language(s)')
    return {'out': str(design.out), 'languages': written, 'pages': str(kept) if kept else None}
