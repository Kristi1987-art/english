use strict; use warnings;
binmode(STDOUT, ':raw');
my $f = shift || "index.html";
open(my $in,'<:raw',$f) or die $!; my $s = do { local $/; <$in> }; close $in;

# --- вырезаем куски ---
my ($groups) = $s =~ /const GROUPS = \[(.*?)\n\];/s or die "no GROUPS";
my ($tricky) = $s =~ /const TRICKY = \[(.*?)\n\];/s or die "no TRICKY";
my ($phr)    = $s =~ /const PHRASES = \[(.*?)\n\];/s or die "no PHRASES";
my ($txt)    = $s =~ /const TEXTS = \[(.*?)\n\];/s  or die "no TEXTS";
my ($nopic)  = $s =~ /const NO_PIC = new Set\(\[(.*?)\]\);/s or die "no NO_PIC";

# --- слова по группам ---
my (%wordOf, %grpLetters, %seen, @dups, %wordGrp);
my $g = 0; my $inWords = 0;
for my $line (split /\n/, $groups) {
  if ($line =~ /^\s*id:(\d+),/) { $g = $1; $inWords = 0; next; }
  $inWords = 1 if $line =~ /^\s*words:\[/;
  if (!$inWords && $line =~ /\{\s*l:'([a-z_0-9]+)'/) { push @{$grpLetters{$g}}, $1; }
  if ($inWords && $line =~ /\{\s*w:'([a-zA-Z']+)'/) {
    my $w = $1;
    push @dups, "$w (гр.$wordGrp{$w} и гр.$g)" if $seen{$w}++;
    $wordOf{$w} = $g; $wordGrp{$w} //= $g;
  }
}
my @tw = $tricky =~ /\{\s*w:'([a-zA-Z']+)'/g;
my %isTricky = map { lc($_) => 1 } @tw;
my %tGrp; while ($tricky =~ /\{\s*w:'([a-zA-Z']+)',\s*g:(\d+)/g) { $tGrp{lc $1} = $2; }

my %noPic = map { $_ => 1 } ($nopic =~ /'([a-z']+)'/g);

# --- буквы, открытые к концу группы N ---
my %openAt;
for my $n (1..8) { for my $k (1..$n) { $openAt{$n}{$_} = 1 for @{$grpLetters{$k}}; } }

# --- разбивка слова на звуки (повторяет split() из приложения) ---
my @DIG = qw(ck ss ll ff ai oa ie ee or oo ng ch sh th qu ou oi ue er ar);
my %DIG = map { $_ => 1 } @DIG;
sub magicIndex { my ($w)=@_; return -1 if length($w)<4 || substr($w,-1) ne 'e';
  my $v = substr($w,-3,1); my $c = substr($w,-2,1);
  return -1 unless $v =~ /[aeiou]/; return -1 if $c =~ /[aeiou]/; return length($w)-3; }
sub splitw { my ($w)=@_; my $m = magicIndex($w); my $end = $m>=0 ? $m : length($w);
  my @o; my $i=0;
  while ($i < $end) { my $pair = substr($w,$i,2);
    if ($i+1 < $end && $DIG{$pair}) { push @o,$pair; $i+=2; } else { push @o,substr($w,$i,1); $i++; } }
  if ($m>=0) { push @o, substr($w,$m,1).'_e'; push @o, substr($w,$m+1,1); }
  return @o; }
my %DOUBLE = map { $_=>1 } qw(ck ss ll ff);

print "СЛОВ ВСЕГО: ".scalar(keys %wordOf)."   НЕВИДИМОК: ".scalar(@tw)."\n";
print "по группам: "; for my $n (1..8) { my $c = grep { $wordOf{$_}==$n } keys %wordOf; print "$n:$c "; } print "\n\n";

print "!! ДУБЛИ СЛОВ: @dups\n\n" if @dups;

# --- 1. каждое слово читается на своей группе ---
my @bad;
for my $w (sort keys %wordOf) {
  my $n = $wordOf{$w};
  # у слов с явным s:[...] звуки заданы вручную — их пропускаем
  next if $s =~ /w:'\Q$w\E',[^\n]*s:\[/;
  for my $u (splitw($w)) {
    next if $DOUBLE{$u};
    my $base = $u; $base =~ s/^([aeiou])_e$/$1_e/;
    push @bad, "$w (гр.$n): звук '$u' ещё не пройден" unless $openAt{$n}{$base};
  }
}
print @bad ? "!! СЛОВА ИЗ НЕПРОЙДЕННЫХ ЗВУКОВ:\n".join("\n",@bad)."\n\n" : "OK: все слова читаются пройденными звуками\n\n";

# --- 2. каждое слово фраз и текстов где-то преподано ---
my @lines;
push @lines, $1 while $phr =~ /en:'([^']*)'/g;
while ($txt =~ /lines:\[(.*?)\]/gs) { my $b=$1; push @lines, $1 while $b =~ /'([^']*)'/g; }
my %untaught;
for my $l (@lines) { for my $tok (split /\s+/, $l) {
  my $w = lc $tok; $w =~ s/[^a-z']//g; next unless $w;
  next if $isTricky{$w} || $wordOf{$w};
  $untaught{$w}++; } }
print %untaught
  ? "!! ВО ФРАЗАХ И ТЕКСТАХ ЕСТЬ, В СЛОВАХ НЕТ:\n  ".join(', ', map {"$_ x$untaught{$_}"} sort keys %untaught)."\n\n"
  : "OK: каждое слово фраз и текстов есть в списке слов или невидимок\n\n";

# --- 3. картинки: сколько слов доступно для забега на каждой группе ---
print "картинок в забеге по группам: ";
for my $n (1..8) { my $c = grep { $wordOf{$_} <= $n && !$noPic{$_} } keys %wordOf; print "$n:$c "; }
print "\n";
print "невидимок открыто по группам: ";
for my $n (1..8) { my $c = grep { $tGrp{$_} <= $n } keys %tGrp; print "$n:$c "; }
print "\n";
