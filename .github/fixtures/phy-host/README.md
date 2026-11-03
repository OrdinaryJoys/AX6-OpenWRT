# Pinned SSDK Source Fixture

This is source data freshly archived from the local verified Git object
d9a196497ecee2530722d906e0efe1b7408b6ef6, including the complete 692-file tree
and its original license material. SOURCE.json records the Git tree, exact
uncompressed archive and compressed bytes. The preparation inventory is also
checked against the previously reviewed complete source contract.

Public mirror retrieval was unavailable during this bounded host validation.
This fixture avoids changing the vendor pin or executing a remote installer.
No binary, generated test program or successful firmware was reused from an
old CI run. Archive members are never executed: tests extract whole functions
and freshly compile their host models using GCC11 in the new run.

Only the fixed 37-patch PHY049 subset is prepared. The current source's 050
patch is admitted by hash but deliberately excluded and explicitly reported;
this smoke does not qualify SSDK050, the current 38-layer driver, target ABI,
firmware, hardware retirement or performance. The firmware lock is unchanged.
