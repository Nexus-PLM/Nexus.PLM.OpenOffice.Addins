using Nexus.PLM.Addin.Sdk.Translators;
using Nexus.PLM.Addin.Sdk.Translators.Testing;
using Xunit;

namespace Nexus.PLM.OpenOffice.Translators.Tests;

/// <summary>
/// Contract tests for this repo's <c>translators/translators.json</c>. Ownership is by input
/// format: the LibreOffice repo owns odt-input; the ODF spreadsheet and presentation inputs
/// live here, still driven through LibreOffice headless on the server.
/// </summary>
public class OpenOfficeManifestTests : ManifestContractTests
{
    /// <inheritdoc/>
    protected override string ManifestPath =>
        Path.Combine(AppContext.BaseDirectory, "translators", TranslatorManifest.FileName);

    /// <summary>The three keys reserved in the Services ownership table.</summary>
    [Fact]
    public void CarriesTheThreeReservedKeys() =>
        Assert.Equal(
            ["odp_to_pdf", "ods_to_pdf", "ods_to_xlsx"],
            Load().Translators.Select(t => t.Key).OrderBy(k => k).ToArray());

    /// <summary>Nothing here reads odt — that input family is the LibreOffice repo's.</summary>
    [Fact]
    public void NothingReadsOdt() =>
        Assert.DoesNotContain(Load().Translators,
            t => t.InputMimeType == "application/vnd.oasis.opendocument.text");

    /// <summary>Every entry leans on the soffice --outdir basename contract (see the
    /// manifest's header comment); hold the exact argument shape.</summary>
    [Fact]
    public void EveryEntryUsesTheSofficeOutdirBasenameContract()
    {
        foreach (var t in Load().Translators)
        {
            Assert.Equal("${ENV:LIBREOFFICE_CMD}", t.Command);
            var args = t.Args;
            Assert.Equal("--headless", args[0]);
            Assert.Equal("--convert-to", args[1]);
            Assert.Equal(t.OutputFileExtension.TrimStart('.'), args[2]);
            Assert.Equal("--outdir", args[3]);
            Assert.Equal("${tempdir}", args[4]);
            Assert.Equal("${input}", args[5]);
            Assert.NotNull(t.InputFileExtension);
        }
    }
}
